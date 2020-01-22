Nordic's nRF91 series has a mechanism for storing [TLS credentials](https://infocenter.nordicsemi.com/index.jsp?topic=%2Fref_at_commands%2FREF%2Fat_commands%2Fmob_termination_ctrl_status%2Fcmng_set.html) securely on the "modem side" of the SoC. The purpose of this project is to provide a proof-of-concept process for writing these credentials efficiently -- using only the SWD interface and without invoking a compiler.
### About
There are several reasons why compiling TLS credentials into production firmware is not a good idea:
* The application must copy the credentials to the modem side of the SoC so they end up occupying space on both cores
  * CA certificates can approach 4KB in length (in addition to the server cert and private key)
  * This also means that the application has to contain extra code to perform the copying
* Key material that is part of the application doesn't benefit from all of the extra security that is provided by the modem core
* Compiling credentials into application hex files requires generating unique application hex files for every device 

These disbenefits are fine during development but ideally a production server would require only the current version of the application firmware, credentials to use for the SoC, and an SWD interface for programming.

This project consists of two components:
1. A prebuilt firmware hex file (that can be compiled using the [nRF Connect SDK](http://developer.nordicsemi.com/nRF_Connect_SDK/doc/latest/nrf/index.html)) that is responsible for writing a list of credentials to the modem side.
1. A Python command line interface that adds credentials to the prebuilt hex file, programs it to the device, allows it to run, verifies that it completed successfully, and then erases it.

This two-step process allows all devices to run the same application hex file and uses Python to do the heavy lifting instead of requiring a full toolchain with a compiler. The extra step to write the credentials should only add on the order of tens of seconds to the overall programming process.
### Requirements
The **intelhex** module is used for working with the hex files and the excellent **pynrfjprog** is used to program the SoC. Requirements can be installed from the command line using pip:
```
$ cd cred
$ pip3 install --user -r requirements.txt
```
### Usage
The command line interface can be modified to add additional capabilties. The existing functionality is pretty comprehensive:
```
$ python3 cred.py --help
usage: cred [-h] [-i PATH_TO_IN_FILE] [-o PATH_TO_OUT_FILE]
            [-d FW_EXECUTE_DELAY] [-s JLINK_SERIAL_NUMBER] [--sec_tag SEC_TAG]
            [--psk PRESHARED_KEY] [--psk_ident PRESHARED_KEY_IDENTITY]
            [--CA_cert_path CA_CERT_PATH]
            [--client_cert_path CLIENT_CERT_PATH]
            [--client_private_key_path CLIENT_PRIVATE_KEY_PATH]

A command line interface for managing nRF91 credentials via SWD.

optional arguments:
  -h, --help            show this help message and exit
  -i PATH_TO_IN_FILE, --in_file PATH_TO_IN_FILE
                        read existing hex file instead of generating a new one
  -o PATH_TO_OUT_FILE, --out_file PATH_TO_OUT_FILE
                        write output from read operation to file instead of
                        programming it
  -d FW_EXECUTE_DELAY, --fw_delay FW_EXECUTE_DELAY
                        delay in seconds to allow firmware on nRF91 to execute
  -s JLINK_SERIAL_NUMBER, --serial_number JLINK_SERIAL_NUMBER
                        serial number of J-Link
  --sec_tag SEC_TAG     sec_tag to use for credential
  --psk PRESHARED_KEY   add a preshared key (PSK) as a string
  --psk_ident PRESHARED_KEY_IDENTITY
                        add a preshared key (PSK) identity as a string
  --CA_cert_path CA_CERT_PATH
                        path to a root Certificate Authority certificate
  --client_cert_path CLIENT_CERT_PATH
                        path to a client certificate
  --client_private_key_path CLIENT_PRIVATE_KEY_PATH
                        path to a client private key

WARNING: nrf_cloud relies on credentials with sec_tag 16842753.
```
A set of credentials that use the same sec_tag can be written to the SoC in a single step:
```
$ python3 cred.py --sec_tag 1234 --psk_ident nrf-123456789012345 --psk CAFEBABE
```
If PEM or CRT files are required then they are specified by file path instead of pasted onto the command line. If more than one sec_tag is required then they can be added by writing the first hex file to a file and then using that file as an input on successive iterations. Here the second invocation adds to the hex file from the first and then writes to the SoC:
```
$ python3 cred.py --sec_tag 1234 --psk_ident nrf-123456789012345 --psk CAFEBABE -o multi_cred.hex
$ python3 cred.py --sec_tag 3456 -i multi_cred.hex --CA_cert_path ca_file.crt
```
The Python program waits five seconds after programming the hex file to allow it to process the credentials and then write a result code to a fixed location in the nRF91's flash memory. This result code is then read to verify that hex file had time to complete its task. If the defaul delay is not long enough then a longer value can be specified via the **--fw_delay** argument.

The prebuilt hex file can be modifed and compiled by moving this repo to the "ncs/nrf/samples/nrf9160" directory and building it as usual.
### Limitations
The ability to add credentials to a file and then read from that file to add additional credentials on the next invocation is half-baked because credentials are not parsed and verified.
