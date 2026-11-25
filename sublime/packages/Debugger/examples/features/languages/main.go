// Go: the same small program as the other languages.
//
// Break on the `return` line of `totalPrice` to see inline values, step out to see what it
// returned, and start with the argument `fail` to stop on a panic.
package main

import (
	"fmt"
	"math"
	"os"
	"strconv"
)

type Item struct {
	Name     string
	Price    float64
	Quantity int
}

func totalPrice(items []Item, taxRate float64) float64 {
	subtotal := 0.0
	for _, item := range items {
		line := item.Price * float64(item.Quantity)
		subtotal += line
	}
	tax := subtotal * taxRate
	total := subtotal + tax
	return math.Round(total*100) / 100 // <- breakpoint here
}

func parsePort(text string) (int, error) {
	port, err := strconv.Atoi(text)
	if err != nil {
		return 0, fmt.Errorf("invalid port %q in config: %w", text, err)
	}
	return port, nil
}

func main() {
	items := []Item{{"pen", 1.99, 3}, {"book", 18.0, 2}, {"lamp", 17.99, 1}}
	result := totalPrice(items, 0.08)
	fmt.Println("total:", result)

	for _, argument := range os.Args[1:] {
		if argument == "fail" {
			port, err := parsePort("eighty")
			if err != nil {
				panic(err)
			}
			fmt.Println("port:", port)
		}
	}
}
