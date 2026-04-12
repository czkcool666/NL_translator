#!/bin/bash

show_usage() {
    echo "Usage: $0 <SOURCE_DIR> [ANALYZE_CPP]"
    echo ""
    echo "Parameters:"
    echo "  SOURCE_DIR    Source code directory path (required)"
    echo "  ANALYZE_CPP   Analysis file name, default is PA_struct.cpp (optional)"
    echo ""
    echo "Examples:"
    echo "  $0 ../dataset/quadtree_0_1_0_expanded_dealed"
    echo "  $0 ../dataset/quadtree_0_1_0_expanded_dealed analyze_advanced.cpp"
    echo ""
    exit 1
}

if [ $# -eq 0 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    show_usage
fi

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Error: Incorrect number of parameters"
    echo ""
    show_usage
fi

PROJECT_DIR="../Code_Package"  
SOURCE_DIR="$1"                          
LLVM_VERSION="14"                         # LLVM version
SVF_ROOT="$PROJECT_DIR/dependencyLib/SVF-SVF-2.9" 


ANALYZE_CPP="analyze.cpp"
if [ $# -eq 2 ]; then
    ANALYZE_CPP="$2"
    echo "Using specified analysis file: $ANALYZE_CPP"
else
    echo "Using default analysis file: $ANALYZE_CPP"
fi

echo "Validating parameters..."

if [ ! -d "$SOURCE_DIR" ]; then
    echo "Error: Source code directory does not exist: $SOURCE_DIR"
    echo "Please ensure the source code directory path is correct"
    exit 1
fi

if [ ! -f "$PROJECT_DIR/script/SA/$ANALYZE_CPP" ]; then
    echo "Error: Specified analysis file does not exist: $PROJECT_DIR/script/SA/$ANALYZE_CPP"
    echo "Available analysis files:"
    ls -1 "$PROJECT_DIR/script/SA/"*.cpp 2>/dev/null || echo "  No .cpp files found"
    exit 1
fi

if [ ! -d "$SVF_ROOT" ]; then
    echo "Error: SVF root directory does not exist: $SVF_ROOT"
    echo "Please check if the SVF installation path is correct"
    exit 1
fi

C_FILES_COUNT=$(find "$SOURCE_DIR" -maxdepth 1 -name "*.c" | wc -l)
if [ "$C_FILES_COUNT" -eq 0 ]; then
    echo "Warning: No .c files found in source code directory: $SOURCE_DIR"
    echo "Please confirm if the directory path is correct"
    read -p "Continue execution? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Operation cancelled"
        exit 1
    fi
fi

echo "Parameters validated successfully!"
echo "Source code directory: $SOURCE_DIR"
echo "Analysis file: $ANALYZE_CPP"
echo "Found $C_FILES_COUNT C source files"
echo ""

SVF_LLVM_DIR="$SVF_ROOT/svf-llvm"
SVF_CORE_DIR="$SVF_ROOT/svf"
SVF_BUILD_DIR="$SVF_ROOT/Release-build"

if [ ! -d "$SVF_BUILD_DIR" ] || [ ! -f "$SVF_BUILD_DIR/svf/libSvfCore.a" ] || [ ! -d "$SVF_BUILD_DIR/svf-llvm" ]; then
    echo "Error: SVF build directory is invalid or not compiled: $SVF_BUILD_DIR"
    echo "Please check if the following commands have been run in $SVF_ROOT and ensure compilation is successful:"
    echo "  $ cd $SVF_ROOT"
    echo "  $ ./build.sh"
    exit 1
fi

SVF_CORE_LIB="$SVF_BUILD_DIR/svf/libSvfCore.a"
SVF_LLVM_LIB="$SVF_BUILD_DIR/svf-llvm/libSvfLLVM.a"

SOURCE_DIR_NAME=$(basename "$SOURCE_DIR")
OUTPUT_DIR="$SOURCE_DIR/svf_analysis_output"

if [ -d "$OUTPUT_DIR" ]; then
    echo "Cleaning output directory (keeping existing JSON files)..."
    find "$OUTPUT_DIR" -type f ! -name "*.json" -delete 2>/dev/null
else
    echo "Creating output directory: $OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR"
fi

echo "Generating LLVM IR files..."
cd "$SOURCE_DIR" || exit 1

IR_COUNT=0
for src_file in *.c; do
    if [ ! -f "$src_file" ]; then
        echo "Warning: No C source file found"
        continue
    fi
    echo "Processing file: $src_file"
    if clang-$LLVM_VERSION -S -emit-llvm -g -O0 -Xclang -disable-O0-optnone -fno-discard-value-names \
        -D_Float128="long double" \
        "$src_file" -o "$OUTPUT_DIR/${src_file%.c}.ll" 2>/dev/null; then
        ((IR_COUNT++))
    else
        echo "Failed to generate IR: $src_file"
        exit 1
    fi
done

echo "Successfully generated $IR_COUNT LLVM IR files"


echo "Linking all .ll files..."
LINKED_LL_FILE="$OUTPUT_DIR/linked_program.ll"

LLVM_IR_FILES=("$OUTPUT_DIR"/*.ll)
if [ ${#LLVM_IR_FILES[@]} -eq 0 ] || [ ! -f "${LLVM_IR_FILES[0]}" ]; then
    echo "Error: No LLVM IR files found"
    exit 1
fi

if llvm-link-$LLVM_VERSION -S "${LLVM_IR_FILES[@]}" -o "$LINKED_LL_FILE"; then
    echo "All .ll files linked to: $LINKED_LL_FILE"
else
    echo "Failed to link .ll files"
    exit 1
fi

echo "Compiling SVF analysis program..."
cd "$OUTPUT_DIR" || exit 1

if ! pkg-config --exists jsoncpp; then
    echo "Error: jsoncpp library is not installed, please install it (e.g., sudo apt-get install libjsoncpp-dev)"
    exit 1
fi

SVFCORE_LIB=$(find "$SVF_BUILD_DIR" -name "libSvfCore.a")
SVFLLVM_LIB=$(find "$SVF_BUILD_DIR" -name "libSvfLLVM.a")

if [ -z "$SVFCORE_LIB" ] || [ -z "$SVFLLVM_LIB" ]; then
    echo "Error: SVF library files not found, please ensure SVF is correctly compiled"
    exit 1
fi

echo "Found SVF Core library: $SVFCORE_LIB"
echo "Found SVF LLVM library: $SVFLLVM_LIB"

echo "Compiling analysis program..."
if clang++-$LLVM_VERSION -std=c++14 \
    -I "$SVF_LLVM_DIR/include" \
    -I "$SVF_CORE_DIR/include" \
    -I "$SVF_BUILD_DIR/include" \
    -I "/usr/lib/llvm-$LLVM_VERSION/include" \
    $(pkg-config --cflags jsoncpp) \
    "$PROJECT_DIR/script/SA/$ANALYZE_CPP" \
    -o svf_pointer_analysis \
    -Wl,--start-group "$SVFLLVM_LIB" "$SVFCORE_LIB" -Wl,--end-group \
    -L "/usr/lib/llvm-$LLVM_VERSION/lib" \
    -lLLVM -lz -lpthread -ldl -ltinfo -lm -lz3 \
    $(pkg-config --libs jsoncpp); then
    echo "Analysis program compiled successfully"
else
    echo "Failed to compile SVF analysis program"
    exit 1
fi

echo "Running pointer analysis..."
if [ ! -f "$LINKED_LL_FILE" ]; then
    echo "Error: Linked .ll file does not exist: $LINKED_LL_FILE"
    exit 1
fi

echo "Analyzing $(basename "$SOURCE_DIR") project..."
if LD_LIBRARY_PATH="$SVF_BUILD_DIR/lib:$LD_LIBRARY_PATH" \
    ./svf_pointer_analysis "$LINKED_LL_FILE"; then
    echo ""
    echo "=== Analysis completed! ==="
    echo "Source code directory: $SOURCE_DIR"
    echo "Analysis results saved to: $OUTPUT_DIR/analysis_result.json"
    echo "Output directory: $OUTPUT_DIR"
    
    if [ -f "$OUTPUT_DIR/analysis_result.json" ]; then
        FILE_SIZE=$(du -h "$OUTPUT_DIR/analysis_result.json" | cut -f1)
        echo "Result file size: $FILE_SIZE"
    fi
else
    echo "Pointer analysis execution failed"
    exit 1
fi