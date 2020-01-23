/*
 * Copyright (c) 2018 Nordic Semiconductor ASA
 *
 * SPDX-License-Identifier: LicenseRef-BSD-5-Clause-Nordic
 */

/* 
 * Credential storage:
 *
 *  The passwd param from the AT command interface is not included because it doesn't appear
 *  to be used now or in the upcoming modem_key_mgmt library.
 *
 *  The fw_result_code value starts as 0xFFFFFFFF and should be written to a useful
 *  result code once credentials are written. This prevents the credentials from being
 *  written multiple times and allows the result code to be read over SWD if necessary.
 *
 *  [MAGIC_NUMBER (0xCA5CAD1A)]
 *  [int32_t fw_result_code]
 *  [char[] IMEI]
 *  [u8_t num_credentials]
 *  [u32_t nrf_sec_tag_t][u8_t nrf_key_mgnt_cred_type_t][u16_t len][char[] credential]
 *  ...
 *  [u32_t nrf_sec_tag_t][u8_t nrf_key_mgnt_cred_type_t][u16_t len][char[] credential]
 */

#include <zephyr.h>
#include <stdio.h>
#include <uart.h>
#include <string.h>

#include <nrfx_nvmc.h>
#include <at_cmd.h>
#include "nrf_inbuilt_key.h"


#define CRED_PAGE_ADDR      0x2B000
#define FW_RESULT_CODE_ADDR (CRED_PAGE_ADDR + 4)
#define IMEI_ADDR           (FW_RESULT_CODE_ADDR + 4)
#define CRED_COUNT_ADDR     (IMEI_ADDR + 16)
#define FIRST_CRED_ADDR     (CRED_COUNT_ADDR + 1)

#define MAGIC_NUMBER        0xCA5CAD1A
#define ERROR_CRED_COUNT    0xFF
#define BLANK_FW_RESULT     0xFFFFFFFF

#define IMEI_LEN            15


/**@brief Recoverable BSD library error. */
void bsd_recoverable_error_handler(u32_t err)
{
    printk("bsdlib recoverable error: %u\n", err);
}

static int remove_whitespace(char *buf)
{
    size_t i, j = 0, len;

    len = strlen(buf);
    for (i = 0; i < len; i++) {
        if (buf[i] >= 32 && buf[i] <= 126) {
            if (j != i) {
                buf[j] = buf[i];
            }

            j++;
        }
    }

    if (j < len) {
        buf[j] = '\0';
    }

    return 0;
}

static int query_modem(const char *cmd, char *buf, size_t buf_len)
{
    int ret;
    enum at_cmd_state at_state;

    ret = at_cmd_write(cmd, buf, buf_len, &at_state);
    if (ret) {
        strncpy(buf, "error", buf_len);
        return ret;
    }

    remove_whitespace(buf);
    return 0;
}

static void write_fw_result(int result)
{
    nrfx_nvmc_word_write(FW_RESULT_CODE_ADDR, result);
    while (!nrfx_nvmc_write_done_check())
    {
    }
}

static bool write_imei(char *buf)
{
    for (int i=0; i < IMEI_LEN; i++)
    {
        if (!nrfx_nvmc_byte_writable_check(IMEI_ADDR + i, buf[i]))
        {
            return false;
        }
    }

    nrfx_nvmc_bytes_write(IMEI_ADDR, buf, IMEI_LEN);
    while (!nrfx_nvmc_write_done_check())
    {
    }

    return true;
}

static int parse_and_write_credential(u32_t * addr)
{
    int ret;

    nrf_sec_tag_t sec_tag = *(u32_t*)*addr;
    *addr += sizeof(nrf_sec_tag_t);

    nrf_key_mgnt_cred_type_t cred_type = *(u8_t*)*addr;
    *addr += sizeof(nrf_key_mgnt_cred_type_t);

    u16_t len = *(u16_t*)*addr;
    *addr += sizeof(u16_t);

    ret = nrf_inbuilt_key_write(sec_tag, cred_type, (u8_t*)*addr, len);

    *addr += len;

    return ret;
}

static bool write_credentials(void)
{
    /* Ensure that the credentials haven't already been written. */
    int fw_result_code = *(int*)FW_RESULT_CODE_ADDR;
    if (BLANK_FW_RESULT != fw_result_code)
    {
        printk("Exiting because fw_result_code has already been written: %d.\n", fw_result_code);
        return false;
    }

    /* Ensure that there are credentials to write. */
    u8_t cred_count = *(u8_t *)CRED_COUNT_ADDR;
    printk("cred_count %d\n", cred_count);
    if ((0 == cred_count) || (ERROR_CRED_COUNT == cred_count))
    {
        printk("Exiting because there are no credentials to write.\n");
        return false;
    }

    /* Write the credentials. */
    u32_t addr = FIRST_CRED_ADDR;
    for (u32_t i=0; i < cred_count; i++)
    {
        int ret = parse_and_write_credential(&addr);
        if (ret)
        {
            printk("Exiting because credential write failed.\n");
            write_fw_result(ret);
            return false;
        }
    }
    printk("Credentials written.\n");

    /* Record the results in flash. */
    write_fw_result(0x00);
    return true;
}

void main(void)
{
    int  ret;
    u8_t result_buf[32];

    printk("cred started\n");

    /* Power off the modem. */
    ret = query_modem("AT+CFUN=0", result_buf, sizeof(result_buf));
    if (ret)
    {
        printk("ERROR: Failed to set CFUN_MODE_POWER_OFF.\n");
        goto finish;
    }
    else
    {
        printk("Modem set to CFUN_MODE_POWER_OFF.\n");
    }

    ret = query_modem("AT+CGSN", result_buf, sizeof(result_buf));
    if (ret)
    {
        printk("ERROR: Failed to read IMEI.\n");
        goto finish;
    }
    else
    {
        printk("Modem IMEI read.\n");
    }

    if (!write_imei(result_buf))
    {
        printk("ERROR: IMEI not written successfully.\n");
        goto finish;
    }
    else
    {
        printk("OK: IMEI written successfully.\n");
    }

    if (write_credentials())
    {
        printk("OK: Credentials written successfully.\n");
    }
    else
    {
        printk("ERROR: Credentials were not written successfully.\n");
    }

finish:
    while(true)
    {
        /* Loop forever. */
    }
}
