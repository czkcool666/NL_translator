# PtrTrans: Pointer-Aware C-to-Rust Translation via Knowledge Graph and Static Analysis

PtrTrans is a C-to-Rust translation framework that leverages **Knowledge Graph (KG)** construction and **SVF-based pointer analysis** to generate safe, idiomatic Rust code from C projects. Unlike naive LLM-based translation, PtrTrans integrates static analysis results—including pointer ownership, mutability, nullability, and aliasing information—into the translation prompts, enabling the LLM to produce Rust code that respects Rust's ownership and borrowing rules.

## 📁 Project Structure

```
PtrTrans-C2Rust/
├── README.md
├── dataset/
│   ├── crown_dataset/          # Source C projects from Crown benchmark
│   │   ├── avl/                # AVL tree implementation
│   │   ├── binn/               # Binary serialization library
│   │   ├── bst/                # Binary search tree
│   │   ├── buffer/             # Buffer management
│   │   ├── bzip2/              # bzip2 compression
│   │   ├── genann/             # Neural network library
│   │   ├── heman/              # Heightmap utilities
│   │   ├── ht/                 # Hash table
│   │   ├── json_h/             # JSON parser
│   │   ├── libtree/            # Tree data structure
│   │   ├── libzahl/            # Big integer library
│   │   ├── lil/                # Scripting language
│   │   ├── lodepng/            # PNG encoder/decoder
│   │   ├── quadtree/           # Quadtree spatial index
│   │   ├── rgba/               # RGBA image processing
│   │   └── urlparser/          # URL parser
│   ├── parsed_projects/        # Pre-parsed project metadata (entities, relationships, call graphs)
│   ├── Trans_C-Rust-KG/        # Translation results with full KG + pointer analysis (PtrTrans)
│   ├── Trans_not_PA/           # Ablation: translation without pointer analysis
│   ├── Trans_not_PU/           # Ablation: translation without pointer-usage context
│   └── Trans_not_RA/           # Ablation: translation without Rust-oriented annotation
└── script/
    ├── main.py                 # Main entry point for the translation pipeline
    ├── generator.py            # LLM API wrapper (OpenAI GPT-4 / local models via HuggingFace)
    ├── translator.py           # Prompt construction and response extraction for translation
    ├── handcraftPrompt.py      # All prompt templates for translation, error fixing, etc.
    ├── KG_construction.py      # Knowledge Graph construction pipeline
    ├── slicer.py               # Code slicing and call graph extraction via Tree-sitter + LSP
    ├── SA/                     # Static Analysis module (SVF-based)
    │   └── backup/
    │       ├── PA_func.cpp     # SVF pointer analysis for function parameters
    │       ├── PA_struct.cpp   # SVF pointer analysis for struct fields
    │       └── run.sh          # Build & run script for SVF analysis
    └── utils/
        ├── c_parser.py         # C code parsing utilities (Tree-sitter)
        ├── rust_parser.py      # Rust code parsing utilities (Tree-sitter)
        ├── doxygen_extractor.py# Doxygen XML parser for call graph extraction
        ├── macro_expand.py     # Macro expansion via Clang preprocessor
        ├── header_extractor.py # Header file content extraction
        ├── extract_cf.py       # Control flow extraction
        ├── git_manage.py       # Git state management for rollback on failure
        ├── misc_utils.py       # Miscellaneous utilities
        └── Doxyfile            # Doxygen configuration template
```

## 🔧 Environment & Dependencies

### System Requirements

| Dependency | Version | Purpose |
|---|---|---|
| **LLVM/Clang** | **14.0.6** | C-to-LLVM-IR compilation, macro expansion |
| **SVF** | **2.9** | Static Value-Flow Analysis for pointer analysis |
| **Doxygen** | ≥ 1.9 | Call graph extraction from C source code |
| **jsoncpp** | (system package) | JSON output from SVF analysis programs |
| **z3** | (system package) | SMT solver required by SVF |
| **GCC** | ≥ 9.0 | Compilation verification |
| **pkg-config** | (system package) | Build configuration for jsoncpp |

### Python Requirements

| Package | Version | Purpose |
|---|---|---|
| **Python** | ≥ 3.9 | Runtime |
| **tree-sitter** | **0.20.1** | C and Rust source code parsing |
| **openai** | (legacy API, v0.x) | OpenAI GPT API access |
| **tiktoken** | ≥ 0.5 | Token counting for GPT models |
| **transformers** | ≥ 4.30 | Local LLM support (LLaMA, etc.) |
| **torch** | ≥ 2.0 | PyTorch backend for local models |
| **langchain** | ≥ 0.1 | Prompt template formatting |
| **tqdm** | ≥ 4.60 | Progress bars |
| **monitors4codegen** | (multilspy) | Language Server Protocol client for code navigation |

### Installing System Dependencies

**Ubuntu/Debian:**
```bash
# LLVM 14
sudo apt-get install clang-14 llvm-14 llvm-14-dev llvm-14-tools

# Doxygen
sudo apt-get install doxygen

# jsoncpp and z3
sudo apt-get install libjsoncpp-dev libz3-dev

# pkg-config
sudo apt-get install pkg-config
```

### Building SVF 2.9

SVF must be built from source and placed under `dependencyLib/SVF-SVF-2.9`:

```bash
# Download SVF 2.9
wget https://github.com/SVF-tools/SVF/archive/refs/tags/SVF-2.9.tar.gz
tar xzf SVF-2.9.tar.gz
mv SVF-SVF-2.9 dependencyLib/

# Build SVF
cd dependencyLib/SVF-SVF-2.9
./build.sh
```

After building, ensure the following files exist:
- `dependencyLib/SVF-SVF-2.9/Release-build/svf/libSvfCore.a`
- `dependencyLib/SVF-SVF-2.9/Release-build/svf-llvm/libSvfLLVM.a`

### Installing Python Dependencies

```bash
pip install tree-sitter==0.20.1 openai tiktoken transformers torch langchain tqdm
pip install monitors4codegen
```

### Building Tree-sitter Parsers

Tree-sitter language parsers need to be pre-built and placed under `dependencyLib/`:

```bash
# Build C parser
git clone https://github.com/tree-sitter/tree-sitter-c.git
cd tree-sitter-c
# Build the shared library (c_parser.so) and place it in dependencyLib/
```

## 🚀 Usage

### Setting Up the API Key

Edit `script/generator.py` and set your OpenAI API key:

```python
OPENAI_API_KEY = "your-api-key-here"
openai.api_base = "https://api.openai.com/v1"  # or your proxy endpoint
```

### Running the Full Translation Pipeline

```bash
cd script

# Run PtrTrans (full pipeline with KG + pointer analysis)
python main.py --translate_mode Trans_PA --model_name gpt-4o-2024-11-20

# Run LLM-only baseline (no program analysis)
python main.py --translate_mode LLM_only --model_name gpt-4o-2024-11-20

# Ablation: without pointer-usage context
python main.py --translate_mode Trans_not_PU --model_name gpt-4o-2024-11-20

# Ablation: without Rust-oriented annotation
python main.py --translate_mode Trans_not_RA --model_name gpt-4o-2024-11-20
```

### Translation Modes

| Mode | Description |
|---|---|
| `Trans_PA` | **Full PtrTrans**: KG construction + SVF pointer analysis + Rust annotation |
| `LLM_only` | Baseline: LLM translation without any program analysis |
| `Trans_not_PU` | Ablation: no pointer-usage context in prompts |
| `Trans_not_RA` | Ablation: no Rust-oriented annotation in prompts |

### Command-Line Arguments

| Argument | Default | Description |
|---|---|---|
| `--model_name` | `gpt-4o-2024-11-20` | LLM model name (GPT-4, GPT-3.5, or local model) |
| `--model_path` | `""` | Path to local model weights (for non-GPT models) |
| `--root_dir` | `../Code_Package` | Root directory of the project |
| `--translate_mode` | `Trans_not_RA` | Translation mode (see table above) |

## ⚙️ Pipeline Overview

The translation pipeline consists of the following stages:

1. **Macro Expansion** (`KG_construction.py` → `macro_expand.py`)
   - Expands C macros using Clang preprocessor
   - Tags system vs. local code origins

2. **Knowledge Graph Construction** (`KG_construction.py` → `doxygen_extractor.py`)
   - Extracts entities (functions, structs, enums, variables) via Doxygen
   - Builds call graph relationships
   - Performs topological sort for translation ordering

3. **SVF Pointer Analysis** (`SA/backup/run.sh` → `PA_func.cpp`, `PA_struct.cpp`)
   - Compiles C source to LLVM IR via `clang-14`
   - Links all IR files via `llvm-link-14`
   - Runs SVF-based analysis for:
     - **Ownership** inference (Owning vs. Borrowed)
     - **Mutability** analysis (Mutable vs. Immutable)
     - **Nullability** detection
     - **Alias analysis** between function parameters
     - **Struct field usage** patterns

4. **LLM-Based Translation** (`translator.py` → `generator.py`)
   - Translates code units in topological order (callees before callers)
   - Injects pointer analysis results into translation prompts
   - Handles `free` operations (memory deallocation → Rust ownership)

5. **Compilation Verification & Repair** (`main.py`)
   - Verifies translated Rust code compiles (`cargo build`)
   - Iterative error-fixing loop (up to 5 attempts)
   - Git-based rollback on persistent failures
   - Stub generation as fallback

## 📊 Evaluation Dataset

The benchmark uses **16 C projects** from the [Crown](https://github.com/nicovank/Crown) dataset, covering diverse domains:

| Project | Domain |
|---|---|
| avl | AVL tree data structure |
| binn | Binary serialization |
| bst | Binary search tree |
| buffer | Buffer management |
| bzip2 | Data compression |
| genann | Neural network |
| heman | Heightmap processing |
| ht | Hash table |
| json_h | JSON parsing |
| libtree | Tree data structure |
| libzahl | Big integer arithmetic |
| lil | Scripting language interpreter |
| lodepng | PNG image codec |
| quadtree | Spatial index |
| rgba | Image color processing |
| urlparser | URL parsing |

