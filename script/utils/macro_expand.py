import json
import os
import subprocess
import sys
from pathlib import Path
import shlex 
import logging
from tqdm import tqdm
from tree_sitter import Language, Parser
import glob
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====  initial treesitter parser ==== #
PARSER_LOCATION = "../Code_Package/dependencyLib/c_parser.so"
if not os.path.exists(PARSER_LOCATION):
    raise FileNotFoundError(f"Parser file not found at: {PARSER_LOCATION}")
LANGUAGE = Language(PARSER_LOCATION, "c")
parser = Parser()
parser.set_language(LANGUAGE)
# ==================================== #


def parse_compile_command(entry):
    if 'arguments' in entry:
        command_parts = entry['arguments']
    elif 'command' in entry:
        command_parts = shlex.split(entry['command'])
    else:
        raise ValueError("Invalid compile_commands.json format: missing 'command' or 'arguments'")
    
    compiler_args = [part for part in command_parts if part not in ['-c', '-o'] 
                    and not part.endswith('.o') 
                    and not part.endswith('.c')]
    return compiler_args


def create_compile_commands(project_path:Path):

    if (project_path / 'compile_commands.json').exists():
        logger.info("compile_commands.json already exists, skipping generation")
        return
    
    if (project_path / 'Makefile').exists():
        logger.info("Found Makefile, generating compile_commands.json using Bear...")
        try:
            subprocess.run(['make', 'clean'], cwd=project_path, check=False)
            subprocess.run(['bear', 'make'], cwd=project_path, check=True)
        except subprocess.CalledProcessError:
            raise Exception("Error: Failed to run 'bear make'")
    
    elif (project_path / 'CMakeLists.txt').exists():
        logger.info("Found CMakeLists.txt, generating compile_commands.json using CMake...")
        build_dir = project_path / 'build'
        
        if build_dir.exists():
            logger.info("Cleaning CMake build directory...")
            import shutil
            shutil.rmtree(build_dir)
        build_dir.mkdir(exist_ok=True)
        
        try:
            subprocess.run(['cmake', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '..'], 
                         cwd=build_dir, check=True)
            if (build_dir / 'compile_commands.json').exists():
                subprocess.run(['cp', 'build/compile_commands.json', '.'], 
                             cwd=project_path, check=True)
        except subprocess.CalledProcessError:
            raise Exception("Error: Failed to generate compile_commands.json with CMake")
    else:
        logger.error(f"Error: Neither Makefile nor CMakeLists.txt found in the project directory: {os.path.basename(project_path)}")
        sys.exit(1)

def expand_macros(project_path:Path, output_dir:Path):

    output_dir.mkdir(exist_ok=True)
    
    compile_commands_path = project_path / 'compile_commands.json'
    if not compile_commands_path.exists():
        compile_commands_path = project_path / 'build' / 'compile_commands.json'  
    if not compile_commands_path.exists():
        raise FileNotFoundError(f"Error: compile_commands.json not found in {project_path} or {project_path}/build")
    
    with open(compile_commands_path) as f:
        compile_commands = json.load(f)
    
    if not compile_commands:
        raise ValueError(f"Error: compile_commands.json is empty in {project_path}")
    
    
    for entry in compile_commands:
        file_path = entry['file']
        
        directory = entry['directory']
        
        try:
            compiler_args = parse_compile_command(entry)
            output_file = output_dir / (Path(file_path).name)
            preprocessor_cmd = ["clang", '-E', file_path] + compiler_args[1:] + ['-o', str(output_file)]

            subprocess.run(preprocessor_cmd, cwd=directory, check=True)
        except (ValueError, subprocess.CalledProcessError) as e:
            print(f"Warning: Failed to process {file_path}: {str(e)}")
            continue

def format_start(expanded_dir):
    output_dir = str(expanded_dir.parent / f"{expanded_dir.name}_dealed")
    os.makedirs(output_dir, exist_ok=True)
    expanded_c_files = glob.glob(os.path.join(expanded_dir, '*.c'))
    for c_file in expanded_c_files:
        output_file = os.path.join(output_dir, os.path.basename(c_file))
        
        with open(c_file, 'r') as f:
            code_content_temp = f.read()
            
        code_content = code_preprocessor(code_content_temp)
        
         
        tree = parser.parse(bytes(code_content, 'utf8'))
        root_node = tree.root_node
        
        tag_new_code_list = []
        dealed_end_line = -1
        for child_node in root_node.children:
            start_line = child_node.start_point[0]
            end_line = child_node.end_point[0] if child_node.end_point[1]!=0 else child_node.end_point[0]-1
            if end_line <= dealed_end_line: continue
            if child_node.type == "preproc_call" and child_node.end_point[1] == 0: continue
            
            dealed_end_line = end_line
            code_cont_temp = "\n".join(code_content.split("\n")[start_line:end_line+1])
                        
            formated_code = format_code_content(code_cont_temp)
            if formated_code == "": continue
            system_or_local_line = system_or_local_stmt(code_content, start_line)
            tag_new_code_content = system_or_local_line.strip() + "\n" + formated_code
            tag_new_code_list.append(tag_new_code_content)
        
        with open(output_file, 'w') as f:
            f.write("\n".join(tag_new_code_list))
    
    return output_dir
def format_code_content(code_content):
    dealed_code_content = []
    
    lines = code_content.split("\n")
    for line in lines:
        if line.strip() == "": continue
        if line.startswith("# "): continue
        dealed_code_content.append(line)
    code_content = "\n".join(dealed_code_content)
    new_code_content = merge_newlines(code_content)
    return new_code_content
        

def code_preprocessor(code_content):

    lines = code_content.split("\n")
    result = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        if not line.strip().startswith("# "):
            result.append(line)
            i += 1
            continue

        if i > 0 and i < len(lines) - 1:
            prev_line = lines[i-1]
            next_line = lines[i+1]
            

            next_has_leading_space = next_line.startswith(" ") or next_line.startswith("\t")
            if (not prev_line.strip().endswith(";") and 
                not prev_line.strip().endswith("{") and 
                not prev_line.strip().endswith("}") and
                next_has_leading_space):
                
                last_result_idx = len(result) - 1
                while last_result_idx >= 0 and not result[last_result_idx].strip():
                    last_result_idx -= 1
                
                if last_result_idx >= 0:
                    result[last_result_idx] = result[last_result_idx].strip() + " " + next_line.strip()
                    i += 2
                    continue
        
        result.append(line)
        i += 1
    
    return "\n".join(result)


def header_extractor(expanded_dealed_dir):
    expanded_c_files = glob.glob(os.path.join(expanded_dealed_dir, '*.c'))
    
    _all_h_code_cont = []
    for c_path in expanded_c_files:
        with open(c_path, 'r') as f:
            code_content = f.read()
            
        tree = parser.parse(bytes(code_content, 'utf8'))
        root_node = tree.root_node
        _c_content, _h_content = traverse_root_node(root_node, code_content)
        _all_h_code_cont.extend(_h_content)
        with open(c_path, 'w', encoding='utf-8') as f:
            f.write("#include \"all_include.h\"\n")
            f.write("\n".join(_c_content))


    seen_contents = set()
    unique_h_code_cont = []
    
    for item in _all_h_code_cont:
        if item['noIndent_code_cont'] not in seen_contents:
            seen_contents.add(item['noIndent_code_cont'])
            unique_h_code_cont.append(item)
    
    h_content = [cont['code_tag'] + "\n" + cont['code_cont'] for cont in unique_h_code_cont ]       
    with open(os.path.join(expanded_dealed_dir, "all_include.h"), 'w', encoding='utf-8') as f:
        f.write("\n".join(h_content))


def traverse_root_node(root_node, code_content):
    _c_content = []
    _h_content = []
    
    for current_node in root_node.children:    
        start_line = current_node.start_point[0]
        end_line = current_node.end_point[0] if current_node.end_point[1]!=0 else current_node.end_point[0]-1
            
        code_cont = "\n".join(code_content.split("\n")[start_line:end_line+1])

        if current_node.type == current_node.text.decode("utf8") or current_node.type in ['comment']: continue
        type_code_line_stmt = SYSTEM_OR_LOCAL(code_content, start_line)
        path = os.path.basename(type_code_line_stmt.split(": ")[1].strip().strip(']'))
        if path.endswith(".h"):
            noIndent_code_cont   = " ".join(code_cont.split())            
            _h_content.append({"code_tag":type_code_line_stmt, "code_cont":code_cont, "noIndent_code_cont":noIndent_code_cont, "path":path})
        else:
            parsedCode = type_code_line_stmt + "\n" + code_cont
            _c_content.append(parsedCode)
            
            

            
    return _c_content, _h_content
    
    
def merge_newlines(code_cont):
    lines = code_cont.split("\n")
    merged_lines = []
    i = 0
    
    while i < len(lines):
        current_line = lines[i].strip()
        # Skip empty lines
        if not current_line:
            merged_lines.append(lines[i])
            i += 1
            continue
            
        # If line ends with semicolon or curly brace, it's complete
        if current_line.endswith(';') or current_line.endswith('{') or current_line.endswith('}') or current_line.endswith('for') \
            or current_line.startswith('#'):
            merged_lines.append(lines[i])
            i += 1
            continue
            
        # Start merging incomplete lines
        merged_line = lines[i]
        while i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if not next_line:  # Skip empty lines
                i += 1
                continue
                
            merged_line += ' ' + next_line
            i += 1
            
            if next_line.endswith(';') or next_line.endswith('{') or next_line.endswith('}'):
                break
                
        merged_lines.append(merged_line)
        i += 1
        
    return '\n'.join(merged_lines)
            


def system_or_local_stmt(code_cont, code_start_line):
    code_cont_list = code_cont.split("\n")
    for i in range(code_start_line, -1, -1):
        line = code_cont_list[i]
        
        if line.startswith('# '):
            parts = line.split()
            if len(parts) >= 3:
                file_name = parts[2].strip('"')
                
                if len(parts) >= 4 and parts[3] == '3':
                    is_system_header = True
                else:
                    is_system_header = file_name.startswith('/usr/') or file_name.startswith('<')

                if is_system_header:
                    return f"// [SYSTEM: {file_name}]\n"
                else:
                    return f"// [LOCAL: {file_name}]\n"              
    return ""


def SYSTEM_OR_LOCAL(code_cont, code_line):
    code_cont_list = code_cont.split("\n")
    
    for i in range(code_line, -1, -1):
        line = code_cont_list[i]
        
        if line.strip().startswith("//"):
            if "LOCAL:" in line:
                return line
            elif "SYSTEM:" in line:
                return line
    return "LOCAL:"
    
    
def compile_c_files(directory_path:str):
    expanded_c_files = glob.glob(os.path.join(directory_path, '*.c'))
    
    successful_files = []
    failed_files = []
    
    for c_file in tqdm(expanded_c_files):
        cmd = ["clang", "-c", "-fno-builtin", "-fno-inline","-O2", "-Xclang", "-disable-llvm-passes", str(c_file),  "-o",  "/dev/null"
]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False 
            )
            
            if result.returncode == 0:
                successful_files.append(str(c_file))
            else:
                failed_files.append(str(c_file))
                logging.info(f"Failed: {c_file}")
        
        except Exception as e:
            failed_files.append(str(c_file))
            logging.info(f"Error: {c_file}, {str(e)}")
    
    logging.info("\nCompile Summary:")
    logging.info(f"Success: {len(successful_files)} files")
    logging.info(f"Failed: {len(failed_files)} files")
        
       

    
if __name__ == "__main__":
    pass