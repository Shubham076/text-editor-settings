// Node: the same small program as the other languages.
//
// Break on the `return` line of `totalPrice` to see inline values, step out to see what it
// returned, and start with the argument `fail` to stop on an error that has a cause.

class Item {
	constructor(name, price, quantity) {
		this.name = name;
		this.price = price;
		this.quantity = quantity;
	}
}

function totalPrice(items, taxRate) {
	let subtotal = 0;
	for (const item of items) {
		const line = item.price * item.quantity;
		subtotal += line;
	}
	const tax = subtotal * taxRate;
	const total = subtotal + tax;
	return Math.round(total * 100) / 100; // <- breakpoint here
}

function parsePort(text) {
	const port = Number.parseInt(text, 10);
	if (Number.isNaN(port)) {
		const cause = new TypeError(`${JSON.stringify(text)} is not a number`);
		throw new Error(`invalid port ${JSON.stringify(text)} in config`, { cause });
	}
	return port;
}

function main() {
	const items = [new Item("pen", 1.99, 3), new Item("book", 18.0, 2), new Item("lamp", 17.99, 1)];
	const result = totalPrice(items, 0.08);
	console.log("total:", result);

	if (process.argv.slice(2).includes("fail")) {
		console.log("port:", parsePort("eighty"));
	}
}

main();
