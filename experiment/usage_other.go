//go:build !darwin && !linux

package experiment

func processUsage() ProcessUsage {
	return ProcessUsage{Error: "process usage collector supports macOS/Linux only", Scope: "unavailable"}
}
