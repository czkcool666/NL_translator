sys_prompt = '''You are a software engineer with 30 years of experience in code translation, specializing in translating an entire C project into a Rust project.
Your goal is to translate the given C project into a Rust project.
'''

pj_tree_trans = '''
Your task is to translate the given C project tree into a Rust project tree and create a mapping between C and Rust files.

## C Project Tree
{c_pj_tree}

## Instructions
1. Translate the C project tree into the Rust project tree (`xx.h` file translate into `common/xx_mod.rs` file), and return ONLY the following two fenced code blocks. Do not include headings, prose, markdown titles, or explanation.

```project_tree
...
Do not generate `main.rs` file!

2. Create a mapping between the C project files and their corresponding Rust files, and provide the file mapping in the following format:
```file_map
{project_name}/src/demo.c -> {project_name}/src/demo.rs
{project_name}/src/common/demo.h -> {project_name}/src/common/demo_mod.rs
...
```
'''


stub_trans = '''
Your task is to translate the given Source C Code into Rust function stubs (signatures only with default returns) according to the provided Contextual Metadata and Static Analysis Results.

## Source C Code
```c
{source_c_code}
```

## CRITICAL STUBBING REQUIREMENTS:
{SA_result}

## Contextual Metadata
- The definitions of the elements used in *Source C Code* have been provided in Rust in other modules as follows:
{rust_code_context}

## Translation Rules (STRICT):
- **CRITICAL: Create stubs ONLY for the functions present in the `## Source C Code`. Do not add any new functions, methods, or `impl` blocks that do not have a direct counterpart in the original C code.**
- Pay special attention to the `## CRITICAL STUBBING REQUIREMENTS` section above.
- Function stubs should:
   - Declare items (e.g., structs, enums, functions, etc.) using the `pub` keyword,
   - Have correctly translated parameter types
   - Provide appropriate return types
   - Return only default values based on the return type
   - Avoid using `*const T` and `*mut T` - use Option<&T> or Option<&mut T> instead 
   - Include necessary dependencies with `use` statements

## Output Format:
Place all function stubs within <rust_stubs> tags:
<rust_stubs>
pub fn example_function(param1: Type1, param2: &mut Type2) -> ReturnType {{
   todo!("Implementation ....");
}}
</rust_stubs>

## Self-Check
Before submitting, verify that you have:
1. Strictly followed ALL requirements specified in the CRITICAL TRANSLATION REQUIREMENTS section
2. Created stubs ONLY for functions in the Source C Code
3. Used proper Rust types (no raw pointers)
'''

SA_code_trans  = '''
Your task is to translate the given Source C Code into Safe and Equivalent Rust Code according to the provided Contextual Metadata and Static Analysis Results.

## Source C Code
```c
{source_c_code}
```
## CRITICAL TRANSLATION REQUIREMENTS:
{SA_result}

## Contextual Metadata
- The definitions of the elements used in *Source C Code* have been provided in Rust in other modules as follows:
{rust_code_context}

## Translation Rules (STRICT):
- **CRITICAL: Translate ONLY the elements present in the `##Source C Code`. Do not add any new functions, methods, `impl` blocks, or logic that does not have a direct counterpart in the original C code.**
- Pay special attention to the `## CRITICAL TRANSLATION REQUIREMENTS` section above.
- The translated Rust code should adhere to the following safety and idiomatic rules:
   - Avoid `unsafe` blocks to ensure memory safety.
   - Avoid using `*const T` and `*mut T`.
   - Declare all items (e.g., structs, enums, functions, etc.) using the `pub` keyword, and include necessary dependencies with `use` statements.
   - For the Borrowed Pointer, use Option<&T> or Option<&mut T>.

## Self-Reflection
Before submitting your translation, verify that you have:
1. Strictly followed ALL requirements specified in the CRITICAL TRANSLATION REQUIREMENTS section
'''


error_fix = '''
Your task is to analyze the given Rust code and fix any errors based on the provided error log. Use the contextual information from the Rust code context and the original C source code to guide your corrections.

## Error Log
- The following error log describes issues found in the Rust code:
{error_log}

## Rust Code to be Fixed
- This is the Rust code that needs to be fixed:
```rust
{to_be_fix_rust_code}
```

## Rust Code Context
- The following Rust code snippets provide additional context for the code to be fixed:
```rust
{rust_code_context}
```

## Instructions:
1. **Analyze the Errors**:
   - Review the error log and identify the specific issues in the `to_be_fix_rust_code`.

2. **Utilize Context**:
   - Use the `rust_code_context` and `source_c_code` to understand the intended functionality and correct the errors.

3. **Fix the Rust Code**:
   - Correct the errors in the `to_be_fix_rust_code` to ensure it compiles and functions as intended.

4. **Return the Fixed Code**:
   - Provide the complete fixed Rust code within the <rust_code> and </rust_code> tags, like this:

<rust_code>
fn greet() {{
    println!("Hello, World!");
}}
</rust_code>
'''

error_related_code = '''
Your task is to analyze a Rust compiler error and identify ONLY the related code snippets from the provided items that help understand the error.

## Error Log
{error_log}

## Primary Item (Contains Error)
```rust
{primary_item}
```

## Available Related Items
```rust
{related_items}
```

## Instructions:
1. **Analyze the Error**: 
   - Carefully examine the error log to understand the specific issue.
   - Identify the exact line(s) causing the error in the primary item.

2. **Identify Related Code**:
   - From the available related items, select ONLY those that are directly relevant to understanding the error.
   - DO NOT include the primary item in your response.
   - Select only items that:
     - Are referenced in the error message
     - Define types or traits mentioned in the error
     - Contain functions/methods called by the error location
     - Define structures or enums involved in the type mismatch

3. **Important**: 
   - Do NOT modify any code
   - Do NOT include the primary item in your response
   - Each related item should be in its own separate code block with its name as a comment

## Output Format:
For each related item, use the following format:

<related_item name="item_name_1">
```rust
pub fn item_name_1(...) {{
    ...
}}
```
</related_item>

<related_item name="item_name_2">
```rust
// Complete code of item_name_2
pub struct item_name_2 {{
    ...
}}
```
</related_item>
...

## Self-Check Before Submitting:
- Have you excluded the primary item from your response?
- Have you included ONLY items relevant to the error?
- Is each related item in its own separate <related_item> block with the correct name attribute?
- Have you preserved the original code without modifications?
'''



rust_error_fix = '''
Your task is to analyze and fix Rust compilation errors based on the provided error description and related code.

## Error Description
{error_description}

## Primary Item (Contains Error)
```rust
{primary_item}
```

## Related Items
```rust
{related_item}
```
## CRITICAL FIX INFORMATION:
{fix_info}

## Correction Steps (STRICT):
1. Carefully analyze the `## Error Description` to understand the root cause of the error (such as type mismatches, lifetime issues, ownership conflicts, etc.).
2. Based on the error analysis, identify the solution strategy, paying special attention to the guidance provided in `## CRITICAL FIX INFORMATION:`. Understand how the code segments in `## Primary Item` and `## Related Items` interact and what needs to be modified.
3. Implement the solution that resolves the error while maintaining the original functionality and idiomatic Rust practices.
4. For the returned rust code (IMPORTANT):
   - DO NOT modify any item names (function names, struct names, enum names, etc.)
   - Return each modified item SEPARATELY in its own code block.
   - Include the COMPLETE item with all its code, not just the modified lines
   - Do NOT include any unmodified items in your response
   - Do not add any new functions, structures, or features beyond what's necessary to fix the error

## Self-Reflection
Before submitting your solution, verify that you have:
1. Strictly followed ALL guidance provided in the CRITICAL FIX INFORMATION section
2. Preserved all original item names
3. Returned each modified item in its own separate code block
4. Avoided using `*const T`, `*mut T` and `unsafe`.
'''

code_trans = '''
Your task is to translate the given *Source C Code* into Safe and Equivalent *Rust Code* according to the *Contextual Metadata*.

## Contextual Metadata
- The definitions of the elements used in *Source C Code* have been provided in Rust in other modules as follows:
{rust_code_context}

## Source C Code
{source_c_code}

## Translation Rules (STRICT):
- The translated Rust code should be Idiomatic and Safe.
- Declare all items (e.g., structs, enums, functions, etc.) using the `pub` keyword, and include necessary dependencies with `use` statements.
- **IMPORTANT**: Only translate what exists in the *Source C Code*. Do not add any additional functions, structs, or logic that is not present in the original code.
- **CRITICAL**: Verify that each element in your Rust translation directly corresponds to an element in the Source C Code. If you find yourself writing code that doesn't have a clear origin in the source, remove it.
- Place the Rust Code that is equivalent to *Source C Code* in the <rust_code> and </rust_code> tags, like this:

<rust_code>
fn greet() {{
    println!("Hello, World!");
}}
</rust_code>

- Place any necessary crate dependencies inside the <toml> and </toml> tags, like this:

<toml>
[dependencies]
rand = "0.8"
</toml>
- If no dependencies are needed, simply respond with: No crate dependencies are required in Cargo.toml.

## Self-check
Verify that: (1) all code is between proper tags, (2) no extra code was added, and (3) each translated element has a direct counterpart in the C source.
'''


code_diff = '''
Your task is to extract unique code elements from `To_be_Added_Code` that do not exist in the `Existing_Code`.

## Existing_Code
{file_code}

## To_be_Added_Code
{trans_code}

## Analysis Instructions (STRICT):
- Compare both code bases to identify elements (functions, structs, methods, etc.) in `To_be_Added_Code` that don't exist in `Existing_Code`.
- Do not modify, reformat, or refactor any content from `To_be_Added_Code`.
- Identify complete syntactic units (functions, structs, methods, etc.) that need to be added

## Output Format
- Place the identified unique parts from `To_be_Added_Code` in the <rust_code> and </rust_code> tags, like this:

<rust_code>
fn greet() {{
    println!("Hello, World!");
}}
</rust_code>

'''


freeJudge = '''
Your task is to analyze the given *Source C Code* and handle any `Memory Deallocation` operations according to the following rules.

## Source C Code
{source_c_code}


## Called C Code Context
- The following C code snippets are called by the *Source C Code* and provide additional context for analysis:
{called_c_code_context}

## Point To Result
- The following describes the pointer relationships for parameters in the *Source C Code*:
{pointToInfo}

## Instructions:
1. **Analyze**:
   - Analyze the memory deallocation logic within the *Source C Code*.
   - Pay special attention to lines marked with "// NOTE: ...". Any line with a "// NOTE: ..." comment MUST be completely removed from the code.

2. **Handle Memory Deallocation Operations**:
   - **Whole Code as Memory Deallocation Operation**: 
     - If the entire *Source C Code* consists solely of a `Memory Deallocation` operation, respond with: "Free operation only."

   - **Contains Memory Deallocation Operation**:
     - If the *Source C Code* contains one or more `Memory Deallocation` operations, identify and remove all `Memory Deallocation` operations from the code.
     - Return the COMPLETE modified *Source C Code* without `Memory Deallocation` operations within the following tags. Include ALL functions from the original Source C Code, even if they were not modified:

   <source_c_code>
   ...
   </source_c_code>

   - **No Memory Deallocation Operation**:
     - If the *Source C Code* does not contain any `Memory Deallocation` operations, return the entire *Source C Code* as is within the following tags:

   <source_c_code>
   ...
   </source_c_code>
   
3. Exclude Context Code: Do not include any code from the Called C Code Context in your response. Focus solely on the Source C Code
'''

extract_signatures = '''
Your task is to extract all function signatures from the provided code, which may be either C or Rust.

## Code
{code}

## Instructions:
1. Analyze the provided code and identify all function signatures.
2. A function signature includes:
   - Function visibility (pub, private)
   - Function name
   - All generic parameters (including lifetime parameters)
   - Parameter list with types
   - Return type

3. Do not include function bodies, only the signatures.
4. Present each extracted signature on its own line, preserving the original formatting.

## Output Format:
Place all extracted function signatures within the following tags:

For Rust code:
<signatures>
pub fn example_function<'a>(param1: Type1, param2: &'a Type2) -> ReturnType
</signatures>

For C code:
<signatures>
int example_function(char* param1, struct Type2* param2)
</signatures>
'''


typdef_var_replace = '''
Your task is to preprocess the given Source C Code by replacing typedefs with their concrete types and localizing global variables.

## Source C Code
```c
{source_c_code}
```
## Transformation Rules (STRICT):
### Typedef Replacement:
- Identify all typedef declarations in the `Source C Code`.
- Replace all usages of typedef names with their actual concrete types throughout the code.
- Example: If `typedef int BOOL;` is defined, replace all occurrences of `BOOL` with `int`.
- For complex typedefs (e.g., function pointers, structs), replace with the complete type definition.

### Global Variable Handling:
- Identify all global variables in the `Source C Code`.
- For non-constant global variables:
  - Convert them to local variables in the functions where they are used.
- For constant global variables (e.g., `const int MAX_SIZE = 100`):
  - Replace all occurrences with the literal value.

Return Replaced Source C Code with the following tag:
<source_c_code>
...
</source_c_code>

### General Rules:
- Maintain the exact functionality of the original code.
- Do not add or remove any functionality.
- Preserve the overall structure of the code.
'''



trans_rust_path_depend = '''
Your task is to generate the correct dependency for the **Caller File** to access code from the **Callee File**.

## Rust Project Tree:
{rust_pj_tree}

## Callee File Path and Code:
{callee_rust_path}

## Caller File Path and Code:
{caller_rust_path}

## Instruction
1. Analyze whether the code in the *Caller File* can access the code in the *Callee File*.
 - If access is possible, respond directly with: **No dependencies are required** and explain why.
 - If access is not possible, generate the correct dependency (e.g., `mod` or `use` statement) and output them in the following format.

<dependency>
// path: xxxx.rs
use callee_file::*;
</dependency>

 - Note: Do not generate dependencies that already exist, and do not make any assumptions during dependency generation!!!
 - Rethink: Reflect on whether the dependencies you have generated are correct and whether they are placed between the tags <dependency> and </dependency> !!!
'''
