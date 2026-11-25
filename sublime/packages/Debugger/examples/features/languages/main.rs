// Rust: the same small program as the other languages.
//
// Break on the last line of `total_price` to see inline values, step out to see what it
// returned, and start with the argument `fail` to stop on a panic.

struct Item {
    name: &'static str,
    price: f64,
    quantity: u32,
}

fn total_price(items: &[Item], tax_rate: f64) -> f64 {
    let mut subtotal = 0.0;
    for item in items {
        let line = item.price * f64::from(item.quantity);
        subtotal += line;
    }
    let tax = subtotal * tax_rate;
    let total = subtotal + tax;
    (total * 100.0).round() / 100.0 // <- breakpoint here
}

fn parse_port(text: &str) -> Result<u16, String> {
    text.parse::<u16>()
        .map_err(|error| format!("invalid port {text:?} in config: {error}"))
}

fn main() {
    let items = [
        Item { name: "pen", price: 1.99, quantity: 3 },
        Item { name: "book", price: 18.0, quantity: 2 },
        Item { name: "lamp", price: 17.99, quantity: 1 },
    ];
    let result = total_price(&items, 0.08);
    println!("total: {result} ({} items, first is {})", items.len(), items[0].name);

    if std::env::args().skip(1).any(|argument| argument == "fail") {
        let port = parse_port("eighty").expect("the port in the config");
        println!("port: {port}");
    }
}
