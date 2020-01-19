Nordic's nRF91 series has a mechanism for storing TLS credentials securely on the "modem side" of the SoC. The purpose of this project is to provide a proof-of-concept process for writing these credentials efficiently -- using only the SWD interface and without invoking a compiler.

### About
There are several reasons why compiling TLS credentials into production firmware is not a good idea:
* the application must copy the credentials to the modem side of the SoC so they end up occupying space on both cores
* and this means that the application has to contain extra code to perform the copying
* credentials such as root CA certificates can approach 4KB in length
* key material that is part of the application doesn't benefit from all of the extra security that is provided by the modem core
* compiling credentials into application hex files requires generating unique application hex files for every device 

These disbenefits are fine during development but ideally a production server would have access to the current version of the application firmware, credentials to use for a particular SoC, and an SWD interface for programming. This project consists of two components:
1. A prebuilt firmware hex file (that can be compiled using the [nRF Connect SDK](http://developer.nordicsemi.com/nRF_Connect_SDK/doc/latest/nrf/index.html)) and is responsible for writing a list of credentials to the modem side.
1. A Python CLI that adds credentials to the prebuilt hex file, programs it to the device, allows it to run, and then erases it.

This two-step process allows all devices to run the same application hex file and uses Python to do the heavy lifting instead of requiring a full toolchain with a compiler.
