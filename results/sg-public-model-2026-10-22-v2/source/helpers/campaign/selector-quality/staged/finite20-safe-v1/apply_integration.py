#!/usr/bin/env python3
"""Create-only composition helper. Safe-only A and safe+one-fill B are explicit."""
from pathlib import Path
def replace_once(path,old,new):
 s=path.read_text();assert s.count(old)==1,'integration anchor mismatch: '+str(path);path.write_text(s.replace(old,new,1))
def integrate(root,include_fill=False):
 root=Path(root);rec=root/'vendor/github.com/ertyoii/transit-routing-go/recommend'
 fields='\n\tFiniteSafe *FiniteSafeConfig `json:"finite20_safe,omitempty"`'
 if include_fill:fields+='\n\tHybridFill *HybridFillConfig `json:"absolute_hybrid_fill,omitempty"`'
 replace_once(rec/'choices.go','type ChoiceConfig struct {','type ChoiceConfig struct {'+fields)
 nested='c.FiniteSafe != nil'+(' || c.HybridFill != nil' if include_fill else '')
 validate='func nestedDeliveryConfig(c ChoiceConfig) bool { return '+nested+' }\n\nfunc (c ChoiceConfig) Validate() error {\n'
 validate+=''' if c.FiniteSafe != nil {
  if '''+('c.HybridFill != nil || ' if include_fill else '')+'''c.Bounded != nil || !c.LeanDelivery || c.DeliveryPolicy != "finite20_safe_v1" || len(c.DeliveryLimits) != 1 || c.DeliveryLimits[0] != 3 || len(c.Groups) != 0 || c.MaxCandidates != c.FiniteSafe.MaxCandidates || c.MaxSubsets != c.FiniteSafe.MaxStates { return fmt.Errorf("finite20-safe named config/limits/guards are inconsistent") }
  return c.FiniteSafe.Validate()
 }
'''
 if include_fill:validate+=''' if c.HybridFill != nil {
  if c.Bounded != nil || !c.LeanDelivery || c.DeliveryPolicy != "bounded_absolute_hybrid_fill_v1" || len(c.DeliveryLimits) != 1 || len(c.Groups) != 0 || c.MaxCandidates != c.HybridFill.Base.MaxCandidates || c.MaxSubsets != c.HybridFill.Base.MaxSubsets { return fmt.Errorf("absolute-hybrid fill named config/limits/guards are inconsistent") }
  if err:=c.HybridFill.Validate();err!=nil{return err}
  if c.DeliveryLimits[0]!=c.HybridFill.Base.Bounded.Limits[0]{return fmt.Errorf("absolute-hybrid fill outer/base requested limits differ")}
  return nil
 }
'''
 replace_once(rec/'choices.go','func (c ChoiceConfig) Validate() error {',validate)
 dispatch='\tif cfg.FiniteSafe != nil { return x.EvaluateFiniteSafe(ctx, q, js, cfg) }\n'
 if include_fill:dispatch+='\tif cfg.HybridFill != nil { return x.EvaluateHybridFill(ctx, q, js, cfg) }\n'
 replace_once(rec/'choices.go','\tif cfg.Bounded != nil {\n\t\treturn x.EvaluateBounded(ctx, q, js, cfg)\n\t}',dispatch+'\tif cfg.Bounded != nil {\n\t\treturn x.EvaluateBounded(ctx, q, js, cfg)\n\t}')
 results='\n\tFiniteSafeChoices *FiniteSafeResult `json:"finite20_safe_choices,omitempty"`'
 if include_fill:results+='\n\tHybridFillChoices *HybridFillResult `json:"absolute_hybrid_fill_choices,omitempty"`'
 replace_once(rec/'quality.go','type Result struct {','type Result struct {'+results)
 main=root/'cmd/familybench/main.go';s=main.read_text();old='(choiceConfig.Bounded != nil || choiceConfig.LeanDelivery)';assert s.count(old)==2,'main shared-checker anchor mismatch';new='(choiceConfig.Bounded != nil || choiceConfig.FiniteSafe != nil'+(' || choiceConfig.HybridFill != nil' if include_fill else '')+' || choiceConfig.LeanDelivery)';main.write_text(s.replace(old,new))
