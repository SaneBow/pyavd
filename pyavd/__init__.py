#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Python library for controlling Android Emulator"""

import socket
import os
import re
import subprocess

EMULATOR_BIN = ''

__author__ = "WANG Xianbo"
__all__ = ["Emulator"]

if not os.environ.get('ANDROID_HOME'):
    print "ANDROID_HOME not found in environment variables"
    raise Exception("pyavd: ANDROID_HOME not defined")

BINDIR = os.path.join(os.environ['ANDROID_HOME'], 'tools')


class Emulator(object):
    def _chdir(func):
        def wrapper(self, *args, **kwargs):
            cwd = os.getcwd()
            os.chdir(BINDIR)
            result = func(self, *args, **kwargs)
            # TODO: if exception raised during func, it won't restore to cwd
            os.chdir(cwd)
            return result
        return wrapper

    @classmethod
    @_chdir
    def list(cls):
        cmd = "bin/avdmanager list avd"
        p = subprocess.Popen(cmd, shell=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
        out, err = p.communicate()
        keys = ['name', 'device', 'path', 'target', 'skin', 'sdcard']
        pattern = ''.join(['\s+{}: (.*?)\n'.format(k) for k in keys])
        values = re.findall(pattern, out, re.DOTALL | re.IGNORECASE)
        return dict(zip(keys, values))

    @classmethod
    @_chdir
    def rename(cls, old_name, new_name):
        cmd = "bin/avdmanager move avd -n {} -r {}".format(old_name, new_name)
        p = subprocess.Popen(cmd, shell=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
        out, err = p.communicate()
        if 'Error:' in out:
            # TODO: consider raising exception here
            return False
        else:
            return True

    def __init__(self, name, port=None, cold_boot=False):
        self._process = None
        self.name = name
        self._args = []
        self._port = port
        if port:
            self._args.extend(['-port', str(port)])
        if cold_boot:
            self._args.extend(['-no-snapshot-load'])

    @_chdir
    def start(self):
        cmd = ["./emulator", "-avd", self.name]
        cmd.extend(self._args)
        p = subprocess.Popen(' '.join(cmd), shell=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
        self._process = p
        return p

    def stop(self, save_on_exit=False):
        if not self._process:
            raise Exception("Cannot stop emulator, haven't started")
        # TODO: this way of killing could cause many problems like leaving lock file behind
        if not save_on_exit:
            self._process.kill()
        else:
            # TODO: sending SIGINT won't work but CTRL-C will work, need further investigation
            self._process.send_signal(2)
        self._process = None
        return True

    def restart(self):
        self.start()
        self.stop()

    @property
    @_chdir
    def port(self):
        """
        If port is specified when initializing, return it
        It not, find console port by emulator name
        """
        # Most simple way is using ps and grep. This method here is to make sure this can be used on Windows
        if self._port:
            return self._port
        cmd = "../platform-tools/adb devices"
        p = subprocess.Popen(cmd, shell=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
        out, err = p.communicate()
        ports = re.findall('emulator-(\d+)', out)
        for port in ports:
            port = int(port)
            ans = ConsoleController(port).get_name()
            if ans.splitlines()[-2] == self.name:
                self._port = port
                self._args.extend(['-port', str(port)])
                return port
        raise Exception('Failed to get port for emulator with name: {}'.format(self.name))

    @property
    @_chdir
    def _adb_state(self):
        cmd = "../platform-tools/adb -s emulator-{} get-state".format(self.port)
        p = subprocess.Popen(cmd, shell=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
        out, err = p.communicate()
        return out[:-1]


    @property
    def status(self):
        # TODO: when divice is on but not started from script, this won't work
        if not self._process:
            return 'off'
        if ConsoleController(self.port).ping() and self._adb_state == 'device':
            return 'on'
        else:
            return 'limbo'

    @property
    def snapshot(self):
        """
        Snapshot management for this emulator
        Usage:
            avd.snapshot.list()
            avd.snapshot.save(name)
            avd.snapshot.load(name)
            avd.snapshot.delete(name)
        """
        return ConsoleController(self.port()).snapshot


class ConsoleController(object):
    def __init__(self, port):
        self.port = port
        self._token = self.get_token()
        self._socket = None

    def recvall(self):
        data = ''
        while not any(w in data for w in ['OK\r\n', 'KO:']):
            data += self._socket.recv(1024)
        return data

    def sendline(self, data):
        self._socket.send("{}\n".format(data))

    def get_token(self):
        if not os.environ.get('HOME'):
            raise Exception("Cannot find home directory, no HOME in environment")
        token_file = os.path.join(os.environ.get('HOME'), '.emulator_console_auth_token')
        if not os.path.exists(token_file):
            return None
        with open(token_file, 'r') as f:
            token = f.read()
        self._token = token
        return token

    def _initiated(func):
        def wrapper(self, *args, **kwargs):
            if not self._socket:
                self.console_init()
            result = func(self, *args, **kwargs)
            return result
        return wrapper

    def _ok_or_raise(boolean=False):
        def real_decorator(func):
            def wrapper(self, *args, **kwargs):
                result = func(self, *args, **kwargs)
                if 'OK' in result:
                    if boolean:
                        return True
                    else:
                        return result
                else:
                    raise Exception('Console command error: \n{}'.format(result))
            return wrapper
        return real_decorator

    def console_init(self):
        s = socket.create_connection(('127.0.0.1', self.port))
        self._socket = s
        ans = self.recvall()
        if 'Authentication required' in ans:
            self._token = self.get_token()
            self.sendline('auth {}'.format(self._token))
            self.recvall()

    @_ok_or_raise(boolean=True)
    @_initiated
    def ping(self):
        self.sendline('ping')
        return self.recvall()

    @_ok_or_raise()
    @_initiated
    def get_name(self):
        self.sendline('avd name')
        return self.recvall()

    # To use decorators in other class, make decorators static
    # After making them static, you can no longer use them to decorate methods of this class
    _initiated = staticmethod(_initiated)
    _ok_or_raise = staticmethod(_ok_or_raise)

    @property
    def snapshot(self):
        cs = self

        class Snapshot(object):
            def __init__(self):
                self._socket = cs._socket
                self.console_init = cs.console_init

            def _parse_to_list(func):
                def wrapper(self):
                    ans = func(self)
                    rows = ans.splitlines()[2:-1]
                    keys = ['id', 'tag', 'size', 'date', 'clock']
                    snapshots = []
                    for r in rows:
                        values = r.split()
                        snapshots.append(dict(zip(keys, values)))
                    return snapshots
                return wrapper

            @_parse_to_list
            @ConsoleController._ok_or_raise(False)
            @ConsoleController._initiated
            def list(self):
                cs.sendline('avd snapshot list')
                return cs.recvall()

            @ConsoleController._ok_or_raise(True)
            @ConsoleController._initiated
            def save(self, name):
                cs.sendline('avd snapshot save {}'.format(name))
                return cs.recvall()

            @ConsoleController._ok_or_raise(True)
            @ConsoleController._initiated
            def load(self, name):
                cs.sendline('avd snapshot load {}'.format(name))
                return cs.recvall()

            @ConsoleController._ok_or_raise(True)
            @ConsoleController._initiated
            def delete(self, name):
                cs.sendline('avd snapshot del {}'.format(name))
                return cs.recvall()

        return Snapshot()
