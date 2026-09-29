#include <stdio.h>
#include <string.h>

typedef struct { char name[16]; int qty; } Item;
typedef struct { Item items[2]; const char *tag; int n; } Box;
typedef union { int i; float f; } Num;

int main(void) {
    Item one = {"item-1", 1};
    Box box;
    strcpy(box.items[0].name, "a");
    box.items[0].qty = 1;
    strcpy(box.items[1].name, "b");
    box.items[1].qty = 2;
    box.tag = "t";
    box.n = 2;
    Item *ptr = &one;
    int arr[3] = {1, 2, 3};
    const char *str = "hello";
    Num num; num.i = 7;
    double d = 2.5;
    int flat[2] = {4, 5};
    Item pair[2] = {{"x", 1}, {"y", 2}};
    printf("%s %d %s %d %s %d %f %d %s\n", one.name, box.n, ptr->name, arr[0], str, num.i, d, flat[0], pair[0].name);
    return 0;
}
