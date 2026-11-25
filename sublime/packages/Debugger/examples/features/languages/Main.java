// Java: the same small program as the other languages.
//
// Break on the `return` line of `totalPrice` to see inline values, step out to see what it
// returned, and start with the argument `fail` to stop on an exception that has a cause.

import java.util.Arrays;
import java.util.List;

public class Main {
	record Item(String name, double price, int quantity) {}

	static double totalPrice(List<Item> items, double taxRate) {
		double subtotal = 0.0;
		for (Item item : items) {
			double line = item.price() * item.quantity();
			subtotal += line;
		}
		double tax = subtotal * taxRate;
		double total = subtotal + tax;
		return Math.round(total * 100) / 100.0; // <- breakpoint here
	}

	static int parsePort(String text) {
		try {
			return Integer.parseInt(text);
		} catch (NumberFormatException error) {
			throw new IllegalStateException("invalid port \"" + text + "\" in config", error);
		}
	}

	public static void main(String[] args) {
		List<Item> items = List.of(new Item("pen", 1.99, 3), new Item("book", 18.0, 2), new Item("lamp", 17.99, 1));
		double result = totalPrice(items, 0.08);
		System.out.println("total: " + result);

		if (Arrays.asList(args).contains("fail")) {
			System.out.println("port: " + parsePort("eighty"));
		}
	}
}
