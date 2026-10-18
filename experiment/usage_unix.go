//go:build darwin || linux

package experiment

import (
	"runtime"
	"syscall"
)

func processUsage() ProcessUsage {
	p := ProcessUsage{Scope: "whole process cumulatively through this snapshot; includes all prior loading, preparation, routing, validation, ranking and any previous artifact serialization/writes; not isolated per-router usage"}
	var r syscall.Rusage
	if err := syscall.Getrusage(syscall.RUSAGE_SELF, &r); err != nil {
		p.Error = err.Error()
		return p
	}
	p.Available = true
	p.MaxRSSBytes = r.Maxrss
	if runtime.GOOS == "linux" {
		p.MaxRSSBytes *= 1024
	}
	p.UserCPUSeconds = float64(r.Utime.Sec) + float64(r.Utime.Usec)/1e6
	p.SystemCPUSeconds = float64(r.Stime.Sec) + float64(r.Stime.Usec)/1e6
	return p
}
