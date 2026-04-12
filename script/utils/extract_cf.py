import json
import os
from tqdm import tqdm
import subprocess
from pathlib import Path
import shutil



def get_dependencies(unique_name, entity_list, relationships, depth=1, visited=None):
    if visited is None:
        visited = set()
    

    if unique_name in visited:
        return []
    
    visited.add(unique_name)
    dependencies = []
    

    for relationship in relationships:
        if relationship['source_unique_name'] == unique_name:
            target_unique_name = relationship['target_unique_name']

            target_info = None
            for entity in entity_list:
                if entity['unique_name'] == target_unique_name:
                    target_info = entity
                    break
            
            if target_info:
                dependency_with_depth = (target_info, depth)
                dependencies.append(dependency_with_depth)
                
                sub_dependencies = get_dependencies(
                    target_unique_name, 
                    entity_list, 
                    relationships, 
                    depth + 1, 
                    visited.copy()  
                )
                dependencies.extend(sub_dependencies)
    
    return dependencies

def extract_cf(project_path, entity_path, relationship_path, output_c_dir):
    with open(entity_path, 'r') as f:
        entity_list = json.load(f)
    with open(relationship_path, 'r') as f:
        relationships = json.load(f)

    for entity in tqdm(entity_list):
        if entity['type'] == 'function':
            if "SYSTEM:" in entity['is_system']: continue
            if entity['line_begin'] == entity['line_end']: continue
            

            
            source_name = entity['name']
            source_unique_name = entity['unique_name']
            all_dependencies = get_dependencies(source_unique_name, entity_list, relationships)
            all_dependencies.insert(0, (entity, 0))
            
            dep_dict = {}
            for dep, depth in all_dependencies:
                unique_name = dep['unique_name']
                if unique_name not in dep_dict or depth > dep_dict[unique_name][1]:
                    dep_dict[unique_name] = (dep, depth)
            

            all_dependencies = list(dep_dict.values())
            all_dependencies.sort(key=lambda x: x[1], reverse=True)
            include_list = []
            code_content = []
            for dep, depth in all_dependencies:
                
                if "SYSTEM:" in dep['is_system']: 
                    path = dep['is_system'].split("// [SYSTEM:")[1].strip().rstrip("]")
                    include_str = f"#include <{path}>"  
                    

                    if include_str not in include_list:
                        include_list.append(include_str)
                    continue

                
                        
                # code_content.insert(0, dep['include_str'])
                code_path = os.path.join(project_path, dep['source_file'])
                with open(code_path, 'r', encoding='utf-8') as f:
                    code_lists = f.read().split('\n')
                line_begin = dep['line_begin']
                line_end = dep['line_end']


                start_line = int(line_begin) -1
                end_line = int(line_end)
                code = f'''// ## {depth} ## {dep['source_file']}\n''' + '\n'.join(code_lists[start_line:end_line])
                    
                code_content.append(code)
                


            all_include_str = "\n".join(include_list)
            code_content.insert(0, all_include_str)
            

            with open(os.path.join(output_c_dir, f"{source_name}.c"), 'w', encoding='utf-8') as f:
                f.write('\n'.join(code_content))
 
 
 
def compile_c_files(directory_path, project_name):
    directory = Path(directory_path)
    

    successful_path = directory.parent / f"{project_name}_successful"
    failed_path = directory.parent / f"{project_name}_failed"
    os.makedirs(successful_path, exist_ok=True)
    os.makedirs(failed_path, exist_ok=True)
    

    c_files = [path for path in directory.glob("**/*.c")]

    successful_files = []
    failed_files = []

    for c_file in tqdm(c_files):
        output_file_o = c_file.with_suffix(".o")
        cmd = ["gcc", "-c", str(c_file), "-o", str(output_file_o)]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            

            relative_path = c_file.relative_to(directory)
            if result.returncode == 0:
                successful_files.append(str(c_file))

                target_path = successful_path / relative_path
                os.makedirs(target_path.parent, exist_ok=True)

                shutil.copy2(c_file, target_path)
            else:
                failed_files.append(str(c_file))

                target_path = failed_path / relative_path
                os.makedirs(target_path.parent, exist_ok=True)

                shutil.copy2(c_file, target_path)

        
        except Exception as e:
            failed_files.append(str(c_file))
            print(f"Error: {c_file}, {str(e)}")
    

    print("\nCompile Summary:")
    print(f"Success: {len(successful_files)} files")
    print(f"Failed: {len(failed_files)} files")
    
    return successful_files, failed_files



                    
                    
                    



