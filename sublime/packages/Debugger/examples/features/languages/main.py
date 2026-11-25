"""Python: the same small program as the other languages.

Break on the `return` line of `total_price` to see inline values, step out to see what it
returned, and start with the argument `fail` to stop on an exception that has a cause.
"""

import sys


class Item:
    def __init__(self, name, price, quantity):
        self.name = name
        self.price = price
        self.quantity = quantity


def total_price(items, tax_rate):
    subtotal = 0.0
    for item in items:
        line = item.price * item.quantity
        subtotal += line
    tax = subtotal * tax_rate
    total = subtotal + tax
    return round(total, 2)  # <- breakpoint here


def parse_port(text):
    try:
        return int(text)
    except ValueError as error:
        raise RuntimeError(f"invalid port {text!r} in config") from error


def main():
    items = [Item("pen", 1.99, 3), Item("book", 18.0, 2), Item("lamp", 17.99, 1)]
    result = total_price(items, 0.08)
    print("total:", result)

    if "fail" in sys.argv[1:]:
        print("port:", parse_port("eighty"))


if __name__ == "__main__":
    main()
