use std::collections::HashMap;

#[derive(Debug)]
struct Item { name: String, qty: i32 }
#[derive(Debug)]
enum Kind { Plain, Tagged(String) }

fn main() {
    let one = Item { name: "item-1".to_string(), qty: 1 };
    let items = vec![Item { name: "a".into(), qty: 1 }, Item { name: "b".into(), qty: 2 }];
    let nums = vec![1, 2, 3];
    let mut map: HashMap<String, i32> = HashMap::new();
    map.insert("a".into(), 1);
    let tup = (1, "x");
    let opt: Option<i32> = Some(5);
    let kind = Kind::Tagged("t".into());
    let plain = Kind::Plain;
    let s = String::from("hello");
    let sl: &[i32] = &nums;
    println!("{:?} {} {} {} {:?} {:?} {:?} {:?} {} {}", one, items.len(), nums.len(), map.len(), tup, opt, kind, plain, s, sl.len());
}
