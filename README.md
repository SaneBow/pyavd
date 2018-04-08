# pyavd
A lightweight Python library for controlling Android Emulator

## Install

```
pip install pyavd
```

## Quick Start

```python
from pyavd import Emulator

avd = Emulator('phone1')
avd.start()
print avd.status
avd.snapshot.save('snapshot1')
avd.snapshot.load('snapshot1')
avd.stop()
```
