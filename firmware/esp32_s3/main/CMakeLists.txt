idf_component_register(
    SRCS "main.cpp"
    INCLUDE_DIRS "."
    REQUIRES driver led_strip freertos esp_system nvs_flash esp_partition spi_flash usb bt
)
