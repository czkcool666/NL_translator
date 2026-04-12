from tqdm import tqdm
from tree_sitter import Language, Parser
import os
from collections import defaultdict, deque
import json
import argparse
import glob
from pathlib import Path
import subprocess
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HeaderExtractor:
    def __init__(self):
        pass
                
        
    def start_parser(self, source_project_path:str, output_project_path:str):
        
        # ====  initial treesitter parser ==== #
        PARSER_LOCATION = "../Code_Package/dependencyLib/c_parser.so"
        if not os.path.exists(PARSER_LOCATION):
            raise FileNotFoundError(f"Parser file not found at: {PARSER_LOCATION}")
        LANGUAGE = Language(PARSER_LOCATION, "c")
        self.parser = Parser()
        self.parser.set_language(LANGUAGE)
        # ==================================== #
        
        self.source_project_path = source_project_path
        
        c_path = os.path.join(self.source_project_path, "*.c")
        c_files = glob.glob(c_path)
        

        
        self.h_content = []
        
        for path in tqdm(c_files, desc="HeaderExtractor"):
            # if "test.c" in path: continue
            
            with open(os.path.join(self.source_project_path, path), 'r', encoding='utf-8') as f:
                self.path_code_content = f.read()
            
            tree = self.parser.parse(bytes(self.path_code_content, 'utf8'))
            root_node = tree.root_node
            _left_content = self.traverse_root_node(root_node, path)
            
            all_code_cont = "\n".join(_left_content)
            with open(os.path.join(output_project_path, os.path.basename(path)), 'w', encoding='utf-8') as f:
                f.write(all_code_cont)
                

            
        
    def traverse_root_node(self, root_node, path):
        _c_content = []
        
        _local_content = []
        _h_content = set() 
        for current_node in root_node.children:
            parsedCode_dict = {}
            
            parsedCode_dict['code_id'] = os.path.basename(path)
            start_line = current_node.start_point[0]
            end_line = current_node.end_point[0]
            code_cont_temp = "\n".join(self.path_code_content.split("\n")[start_line:end_line+1])
            parsedCode_dict['noIndent_code_cont'] = " ".join(code_cont_temp.split())
            code_cont = self.merge_newlines(code_cont_temp)
            
            if current_node.type == current_node.text.decode("utf8"): continue
            if current_node.type in ['comment']: continue
            
            type_code_line_stmt = self.system_or_local_stmt(self.path_code_content, start_line)
            
            if "LOCAL:" in type_code_line_stmt:
                _local_content.append(type_code_line_stmt)
                _local_content.append(code_cont)
                
            elif "SYSTEM:" in type_code_line_stmt:
                system_include_path = self.extract_include_content(type_code_line_stmt)
                if system_include_path:
                     _h_content.add("#include <" + system_include_path + ">") 
        
        return list(_h_content) + _local_content
    
    def system_or_local_stmt(self, code_cont, code_line):
        code_cont_list = code_cont.split("\n")
        
        for i in range(code_line, -1, -1):
            line = code_cont_list[i]

            if line.strip().startswith("//"):
                if "LOCAL:" in line:
                    return line
                elif "SYSTEM:" in line:
                    return line
        return "LOCAL:"

    def compile_c_files(self, directory_path:str):
        directory = Path(directory_path)
        successful_files = []
        failed_files = []
        
        c_files = [path for path in directory.glob("**/*.c")]
        for c_file in tqdm(c_files):

            cmd = ["gcc", "-c", str(c_file), "-o", "/dev/null"]
            
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
    
    def merge_newlines(self, code_cont):
        lines = code_cont.split("\n")
        merged_lines = []
        i = 0
        
        while i < len(lines):
            current_line = lines[i].strip()
            if not current_line:
                merged_lines.append(lines[i])
                i += 1
                continue
            
            if current_line.endswith(';') or current_line.endswith('{') or current_line.endswith('}'):
                merged_lines.append(lines[i])
                i += 1
                continue
                
            merged_line = lines[i]
            while i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if not next_line:  
                    i += 1
                    continue
                    
                merged_line += ' ' + next_line
                i += 1
                
                if next_line.endswith(';'):
                    break
                    
            merged_lines.append(merged_line)
            i += 1
            
        return '\n'.join(merged_lines)

    def extract_include_content(self, type_code_line_stmt):

        if '// [SYSTEM: /usr/include/' not in type_code_line_stmt:
            return ""
        
        path = type_code_line_stmt.strip().split('/usr/include/')[1].rstrip(']')
        
        if path.startswith('x86_64-linux-gnu/'):
            path = path[len('x86_64-linux-gnu/'):]
        
        if path.startswith('gcc/') or '/gcc/' in path:
            path = path.split('/gcc/')[1]
        
        skip_prefixes = [
            'bits/', 'gnu/', 'sys/cdefs.h', 'features.h', 
            'libio.h', 'syslimits.h', 'xlocale.h', 'wchar.h',
            'stdint-intn.h', 'stdint-uintn.h'
        ]
        
        for prefix in skip_prefixes:
            if path.startswith(prefix):
                if path.startswith('bits/'):
                    if 'stdlib' in path:
                        return 'stdlib.h'
                    elif 'string' in path:
                        return 'string.h'
                    elif 'math' in path:
                        return 'math.h'
                    elif 'types' in path or 'typesizes' in path:
                        return 'sys/types.h'
                    elif 'time' in path:
                        return 'time.h'
                    elif 'stdio' in path:
                        return 'stdio.h'
                return ""
        
        if path == 'stdc-predef.h' or path == 'stddef.h':
            return ""
        
        if path == 'x86_64-linux-gnu/bits/libc-header-start.h':
            return ""
        
        if path == '<built-in>' or path == '<command-line>':
            return ""
        
        return path
        
        
if __name__ == "__main__":
    pass