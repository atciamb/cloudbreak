# Bundled Servo library (UNO Q backend only)

These files are from the official Arduino **Servo** library, release **1.3.0**:
https://github.com/arduino-libraries/Servo/tree/1.3.0

- `Servo.h` is the library's public header, unchanged.
- `zephyr/Servo.cpp` and `zephyr/ServoTimers.h` are its Zephyr (Arduino UNO Q) backend. The only change is one line in `Servo.cpp`, which includes `"../Servo.h"` instead of `<Servo.h>`.

They're bundled so the sketch compiles without installing anything from Library Manager. The Arduino IDE compiles everything under a sketch's `src/` folder.

License: GNU LGPL 2.1 (see `LICENSE.txt`). Copyright (c) 2009 Michael Margolis and Arduino.
