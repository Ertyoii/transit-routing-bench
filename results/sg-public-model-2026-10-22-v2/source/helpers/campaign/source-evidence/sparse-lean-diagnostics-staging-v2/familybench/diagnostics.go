package main

import (
	"path/filepath"
	"runtime"
	"time"
	"github.com/ertyoii/transit-routing-bench/experiment"
)

type diagnosticsExport struct {
	Enabled bool `json:"enabled"`
	ElapsedNS int64 `json:"elapsed_ns"`
	AllocatedBytes uint64 `json:"allocated_bytes"`
	WholePhaseNS int64 `json:"whole_phase_ns"`
	InstrumentationNS int64 `json:"instrumentation_ns"`
	Scope string `json:"scope"`
	ResourcesAfter experiment.Resources `json:"resources_after"`
}
func measureDiagnostics(export func() any) (any,diagnosticsExport) {
	if export==nil {return nil,diagnosticsExport{}}
	phaseBegin:=time.Now()
	var before,after runtime.MemStats;runtime.ReadMemStats(&before);begin:=time.Now()
	value:=export();elapsed:=time.Since(begin).Nanoseconds();runtime.ReadMemStats(&after)
	resources:=experiment.SnapshotResources();whole:=time.Since(phaseBegin).Nanoseconds()
	return value,diagnosticsExport{Enabled:true,ElapsedNS:elapsed,AllocatedBytes:after.TotalAlloc-before.TotalAlloc,
		WholePhaseNS:whole,InstrumentationNS:whole-elapsed,
		Scope:"elapsed_ns/allocation delta cover export only; whole_phase_ns additionally includes MemStats and resource snapshots; outside native prepNS/checker prep/historical response clocks; process-start availability includes the prequery phase",
		ResourcesAfter:resources}
}
func sparseDiagnosticsName(name string) bool {
	return name=="ultra_cap_safe_stay_witness_subset_v1"||name=="ultra_subset_local_walk_ties"
}

type fullDiagnosticsEvidence struct {
	File string `json:"file"`
	Export diagnosticsExport `json:"owned_preparation_export"`
	IO experiment.ArtifactIO `json:"artifact_io"`
	ElapsedNS int64 `json:"whole_evidence_phase_ns"`
	AllocatedBytes uint64 `json:"whole_evidence_phase_allocated_bytes"`
	Scope string `json:"scope"`
}
// Compact mode still retains the FULL ORIGINAL owned Preparation evidence from
// THIS exact index after serving. It is source/data/config bound and excluded
// from query clocks, not suppressed or used to provide route answers.
func writeFullDiagnostics(out string,export func() any,binding map[string]any) (*fullDiagnosticsEvidence,error) {
	if export==nil {return nil,nil}
	var before,after runtime.MemStats;runtime.ReadMemStats(&before);begin:=time.Now()
	value,stats:=measureDiagnostics(export)
	payload:=map[string]any{"binding":binding,"preparation":value,"scope":"original full owned SparseIndex.Preparation evidence; emitted after all queries; not a substitute for native proof construction/validity or a served answer"}
	file:="sparse-full-preparation.json";record,e:=experiment.WriteArtifact(filepath.Join(out,file),payload)
	runtime.ReadMemStats(&after)
	return &fullDiagnosticsEvidence{File:file,Export:stats,IO:record,ElapsedNS:time.Since(begin).Nanoseconds(),AllocatedBytes:after.TotalAlloc-before.TotalAlloc,
		Scope:"full same-index proof evidence retained after serving; JSON serialization is NOT streaming and may retain a large buffer/peak; no whole-process memory or kernel speed claim"},e
}
