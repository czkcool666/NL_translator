#include <stdio.h>
#include "json.h"

int main() {
    const char *json_text = "{\"name\":\"John\", \"age\":30, \"city\":\"New York\"}";
    struct json_value_s *value = json_parse(json_text, strlen(json_text));
    
    if (value) {
        printf("JSON parsed successfully\n");
        free(value);
    } else {
        printf("Failed to parse JSON\n");
    }
    
    return 0;
}