cmake_minimum_required(VERSION 3.16)

set(COMPONENTS main espressif__usb_host_vcp espressif__usb_host_ftdi_vcp espressif__usb_host_cdc_acm espressif__led_strip)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ppi_bridge)
