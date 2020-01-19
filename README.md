Nordic's nRF91 series has a mechanism for storing TLS credentials securely on the "modem side" of the SoC. The purpose of this project is to provide a proof-of-concept process for writing these credentials efficiently -- using only the SWD interface and without invoking a compiler.
### About
There are several reasons why compiling TLS credentials into production firmware is not a good idea:
* The application must copy the credentials to the modem side of the SoC so they end up occupying space on both cores
* Plus this means that the application has to contain extra code to perform the copying
* Credentials such as root CA certificates can approach 4KB in length
* Key material that is part of the application doesn't benefit from all of the extra security that is provided by the modem core
* Compiling credentials into application hex files requires generating unique application hex files for every device 

These disbenefits are fine during development but ideally a production server would have access to the current version of the application firmware, credentials to use for the SoC, and an SWD interface for programming. This project consists of two components:
1. A prebuilt firmware hex file (that can be compiled using the [nRF Connect SDK](http://developer.nordicsemi.com/nRF_Connect_SDK/doc/latest/nrf/index.html)) and is responsible for writing a list of credentials to the modem side.
1. A Python command line interface that adds credentials to the prebuilt hex file, programs it to the device, allows it to run, and then erases it.

This two-step process allows all devices to run the same application hex file and uses Python to do the heavy lifting instead of requiring a full toolchain with a compiler. The extra step to write the credentials should only add tens of seconds to the overall programming process.
### Requirements
The intelhex module is used for working with the prebuilt hex file and the excellent pynrfjprog is used to program the SoC. Requirements can be installed from the command line using pip:
```
$ cd at
$ pip3 install --user -r requirements.txt
```
### Usage
The command line interface can be modified to add additional capabilties. The existing functionality is pretty comprehensive:
```
$ python3 cred.py 
usage: cred [-h] [-i PATH_TO_IN_FILE] [-o PATH_TO_OUT_FILE]
            [-d FW_EXECUTE_DELAY] [-s JLINK_SERIAL_NUMBER] [--sec_tag SEC_TAG]
            [--psk PRESHARED_KEY] [--psk_ident PRESHARED_KEY_IDENTITY]
            [--CA_cert_path CA_CERT_PATH]
            [--client_cert_path CLIENT_CERT_PATH]
            [--client_private_key_path CLIENT_PRIVATE_KEY_PATH]
error: sec_tag is required
```
A single set of credentials that use the same sec_tag can be written in a single step:
```
$ python3 cred.py --sec_tag 1234 --psk_ident nrf-123456789012345 --psk CAFEBABE
```
If PEM or CRT files are required then they are specified by file path instead of pasted onto the command line. If more than one sec_tag is required then they can be added by writing the first hex file to a file and then using that file as an input on successive iterations:
```
$ python3 cred.py --sec_tag 1234 --psk_ident nrf-123456789012345 --psk CAFEBABE -o multi_cred.hex
$ python3 cred.py --sec_tag 3456 -i multi_cred.hex --CA_cert_path sample.yaml
```
### Limitations
The ability to write to a file and then read from that file to add to it on the next invocation is half-baked because credentials are not parsed and verified when using an in file.
