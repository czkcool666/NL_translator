import json
import os
import shutil
import subprocess



def load_test_data(_parsed_functional_codePath, _parsed_pj_treePath):
    with open(_parsed_functional_codePath, encoding='utf-8') as f:
        lines = f.readlines()
    repos_info_list = [json.loads(line) for line in lines]
    
    with open(_parsed_pj_treePath, encoding='utf-8') as f:
        repos_pj_tree = f.read()
    return repos_info_list, repos_pj_tree



def obtain_project_tree(root_path):

    if not os.path.exists(root_path):
        print(f"Path Not Exist: {root_path}")
        return []

    pathList = [os.path.basename(root_path)]  
    

    stack = [(root_path, "")]
    
    while stack:
        current_path, current_indent = stack.pop()
        entries = os.listdir(current_path)
        entries.sort()  
        
        for i in range(len(entries)-1, -1, -1):
            entry = entries[i]
            full_path = os.path.join(current_path, entry)
            is_last = (i == len(entries) - 1)
            
            if is_last:
                entry_prefix = "└── "
                new_indent = current_indent + "    "
            else:
                entry_prefix = "├── "
                new_indent = current_indent + "│   "
            
            pathList.append(f"{current_indent}{entry_prefix}{entry}")
            
            if os.path.isdir(full_path):
                stack.append((full_path, new_indent))
    
    return "\n".join(pathList)


if __name__ == "__main__":
    pass


