This project is building majorly on the static analysis results building on Ptr_Trans.  
The link to its repo: https://github.com/FudanSELab/PtrTrans-C2Rust.  
The link to its paper: https://arxiv.org/abs/2510.10956.

## Motivation

Instead of asking the model to discover all relevant program semantics while translating, first use static analysis to collect evidence about the program. To do this, we used rule-based static analysis to infer obvious ownership, mutability, aliasing, and lifetime-related relationships. Then we ask the model to convert that evidence and the source code into a structured semantic understanding. Translation happens only after this intermediate reasoning step.

**The pipeline is roughly:**

**C Source + Static Analysis + Program Context → Structured Semantic Summary → C Source + Semantic Summary + Rust Dependencies → Rust Implementation→ compiler-feedback repair.**

Therefore, the semantic summary captures behavior, field and parameter meanings, memory relationships, side effects, and unresolved uncertainties. Rust generation uses this summary together with translated Rust dependencies, without receiving the original C unit or raw analysis results
