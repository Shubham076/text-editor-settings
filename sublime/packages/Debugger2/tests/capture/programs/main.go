package main

import "errors"

type L4 struct{ Name string; N int }
type L3 struct{ Items []L4; Tag string }
type L2 struct{ Inner L3; Flag bool }
type L1 struct{ Mid L2; Label string }
type Deep struct{ Top L1; Extra map[string][]L4 }

type Shape interface{ Area() float64 }
type Circle struct{ R float64 }
func (c Circle) Area() float64 { return 3.14 * c.R * c.R }

func main() {
	deep := Deep{
		Top:   L1{Mid: L2{Inner: L3{Items: []L4{{"a", 1}, {"b", 2}}, Tag: "t"}, Flag: true}, Label: "L"},
		Extra: map[string][]L4{"k": {{"c", 3}}},
	}
	ptrs := []*L4{{"p", 9}, {"q", 10}}
	nested := [][]L4{{{"x", 1}}, {{"y", 2}}}
	var err error = errors.New("boom")
	var sh Shape = Circle{R: 2}
	println(deep.Top.Label, len(ptrs), len(nested), err, sh)
}
