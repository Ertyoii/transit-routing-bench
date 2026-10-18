package main

import (
	"fmt"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"os"
)

func main() {
	if _, e := experiment.VerifyRoutingLock("."); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
	h, e := experiment.SourceHash(".")
	if e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
	fmt.Println(h)
}
