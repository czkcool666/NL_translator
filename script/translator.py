# from utils.misc_utils import extract_code
from langchain.prompts import PromptTemplate
import re
import os

import handcraftPrompt
from utils.rust_parser import RustParser

""" Using model to make translation """

'''
trans_mode: 1. naive_trans; 2. refined_trans
sub_trans_mode: a. pj_tree_trans; b. file_skeleton_trans; c. function_impl_trans
'''

    
class Translator:
    def __init__(self, args, generator):
        self.args = args
        self.generator = generator
        self.translate_mode = args.translate_mode
        self.promptSelect= PromptDefine()
        self.project_name = args.source_project_name
        self._runLog_path = os.path.join(args.trans_project_path, args.source_project_name + "_runLog.txt")
        self.rust_parser = RustParser(self.args.root_dir)
    
    def _pj_tree_trans(self, c_pj_tree):
        """
        trans the given source project tree to the target project tree, and mkdir this target project tree in `trans_projects`.
        """
        base_prompt = self.promptSelect.pj_tree_trans(c_pj_tree, self.project_name)
        last_error = None
        for attempt in range(3):
            if attempt == 0:
                t_prompt = base_prompt
                prompt_type = "Project Tree Translation"
            else:
                t_prompt = (
                    base_prompt
                    + "\n\nYour previous response could not be parsed. "
                    + "Return ONLY these two fenced code blocks, with no headings, prose, or explanation:\n"
                    + "```project_tree\n"
                    + f"{self.project_name}\n"
                    + "├── Cargo.toml\n"
                    + "├── src\n"
                    + "    ├── demo.rs\n"
                    + "```\n"
                    + "```file_map\n"
                    + f"{self.project_name}/src/demo.c -> {self.project_name}/src/demo.rs\n"
                    + "```\n"
                )
                prompt_type = f"Project Tree Translation Retry {attempt}"

            response = self.generator.get_response(t_prompt)
            self._log_prompt_response(prompt_type, t_prompt, response)
            try:
                return self._extract_pj_tree_map(response)
            except AssertionError as e:
                last_error = e

        raise last_error
    
    def _free_judge(self, source_c_code, called_code_context, pointToInfo):
        """
        judge whether souce code is/include `free` operation
        """
        t_prompt = self.promptSelect.freeJudge(source_c_code.strip(), called_code_context.strip(), pointToInfo)        
        response = self.generator.get_response(t_prompt)
        self._log_prompt_response("Free Judge", t_prompt, response)
        extract_response = self._extract_free_judge(response)
        return extract_response

    def _rust_error_fix(self, error_log, primary_item, related_item, fix_SA_info):
        # source_c_code = ""
        t_prompt = self.promptSelect.rust_error_fix(error_log.strip(), primary_item.strip(), related_item.strip(), fix_SA_info)
        response = self.generator.get_response(t_prompt)
        self._log_prompt_response("Error Fix", t_prompt, response)
        # extract_response = self._extract_fixed_rust(response)
        # response_list = []
        
        response_list,toml_de = self._extract_fixed_rust(response)
        
        fixed_rust_list= []
        for res in response_list:
            definition_names = self.rust_parser.get_rust_definitions(res)
            if len(definition_names) != 0:
                fixed_rust_list.append({tuple(definition_names):res})
            else:
                if len(primary_item.strip().split("\n")) == 1 or res.strip().startswith("use "): # 此时，应该某一行代码出现了错误。例如 use xxx
                    fixed_rust_list.append({("LINE",):res})
                # else:
                #     raise ValueError(f"Invalid response: {res}")
            
        
        return fixed_rust_list,toml_de
    
    def _error_related_code(self, error_log, primary_item, all_items):
        t_prompt = self.promptSelect.error_related_code(error_log, primary_item, all_items)
        response = self.generator.get_response(t_prompt)
        # self._log_prompt_response("Error Fix", t_prompt, response)
        extract_response = self._extract_selected_rust(response)
        return extract_response


    def _code_trans_mock(self, source_c_code, source_c_code_type, rust_depend_metas, code_unique_names, rust_file_code, SA_result):
        write_rust_code = \
'''
pub fn binn_count(ptr: Option<&u32>) -> i32 {
    match binn_get_ptr_type(ptr) {
        1 => {
            if let Some(ptr) = ptr {
                let item = unsafe { &*(ptr as *const BinnStruct) }; // Unsafe block retained for pointer casting
                item.count
            } else {
                -1
            }
        }
        2 => {
            if let Some(ptr) = ptr {
                let pbuf = unsafe {
                    std::slice::from_raw_parts(ptr as *const u8, std::mem::size_of::<u32>())
                };
                binn_buf_count(Some(pbuf))
            } else {
                -1
            }
        }
        _ => -1,
    }
}
'''
        return write_rust_code, "", "", ""


    
    def _code_trans(self, source_c_code, rust_depend_metas, code_unique_names, rust_file_code, SA_result, typedef_var_TAG):
        """
        trans the given source code to the target code
        """
        # 将给定的C code 基于rust_depend_context_code翻译成对应的Rust code.
        # rust_depend_context_code =  "\n==========\n".join(["@Source_c_code:\n" + meta['source_c_code_context'].strip() + "\n@Corresponding translated rust code:\n" + meta['trans_rust_code_context'].strip()
        #                                                  for meta in rust_depend_metas])
        
        if typedef_var_TAG:
            original_source_c_code = source_c_code.strip()
            typedef_var_prompt = self.promptSelect.typdef_var_replace(original_source_c_code)
            extracted_source_c_code = ""
            for attempt in range(3):
                current_prompt = typedef_var_prompt
                if attempt > 0:
                    current_prompt = (
                        typedef_var_prompt
                        + "\n\nYour previous response could not be parsed. "
                        + "Return ONLY the transformed C code wrapped exactly like this:\n"
                        + "<source_c_code>\n...\n</source_c_code>"
                    )
                typedef_var_response = self.generator.get_response(current_prompt)
                extracted_source_c_code = self._extract_free_judge(typedef_var_response, free_Tag=False)
                if extracted_source_c_code:
                    break

            if extracted_source_c_code:
                source_c_code = extracted_source_c_code
            else:
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to extract typedef/global preprocessing response for {code_unique_names}; using original source C code"
                )
                source_c_code = original_source_c_code
        
        rust_depend_context_code =  "\n==========\n".join([meta['trans_rust_code_context'].strip() for meta in rust_depend_metas if meta['trans_rust_code_context'].strip()])
        t_prompt = self.promptSelect.SA_code_trans(source_c_code.strip(), rust_depend_context_code.strip(), SA_result)

        if self.args.translate_mode == "LLM_only":
            t_prompt = t_prompt.replace("- For the Borrowed Pointer, use Option<&T> or Option<&mut T>.","").replace("Avoid using `*const T` and `*mut T`.","")
        
        # if self.args.translate_mode == "Trans_PA":
        #     t_prompt = self.promptSelect.SA_code_trans(source_c_code.strip(), rust_depend_context_code.strip(), SA_result)
        # elif self.args.translate_mode == "LLM_only" or self.args.translate_mode == "Trans_PA_LLM":
        #     t_prompt = self.promptSelect.code_trans(source_c_code.strip(), rust_depend_context_code.strip())
        #     t_prompt = t_prompt.replace("- For the Borrowed Pointer, use Option<&T> or Option<&mut T>.","").replace("Avoid using `*const T` and `*mut T`.","")
        # else:
        #     raise ValueError(f"Invalid translate mode: {self.args.translate_mode}")

        # 尝试生成代码，如果提取不到，则重试
        max_retries = 3  # 最大重试次数
        for attempt in range(max_retries):
            response = self.generator.get_response(t_prompt)
            self._log_prompt_response("Code Translation", t_prompt, response, code_unique_names)
            
            trans_rust_code, toml_depend = self._extract_code_trans(response)
            # 如果提取到了代码，则返回
            if trans_rust_code.strip():
                return trans_rust_code, toml_depend
            
            # 如果是最后一次尝试仍未提取到代码，记录警告日志
            if attempt == max_retries - 1:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to extract Rust code after {max_retries} attempts for {code_unique_names}")
        
        raise ValueError(f"Failed to extract Rust code after {max_retries} attempts for {code_unique_names}")   
        
        # response = self.generator.get_response(t_prompt)
        # self._log_prompt_response("Code Translation", t_prompt, response, code_unique_names)
        
        # trans_rust_code, toml_depend  = self._extract_code_trans(response)
        
        # rust_depend_code = "\n".join([meta['trans_rust_code_context'].strip() for meta in rust_depend_metas])
        # # write_rust_code = trans_rust_code
        # if len(trans_rust_code) != 0:
        #     code_diff_prompt = self.promptSelect.code_diff(rust_depend_code + "\n==========\n" + rust_file_code, trans_rust_code)
        #     code_diff_response = self.generator.get_response(code_diff_prompt)
        #     write_rust_code = self._extract_code_diff(code_diff_response)
        #     self._log_prompt_response("Code Diff", code_diff_prompt, code_diff_response, code_unique_names)
        # else: write_rust_code = trans_rust_code
        
        # return trans_rust_code, toml_depend




    def _stub_trans(self, source_c_code, source_c_code_type, rust_depend_metas, code_unique_names, rust_file_code, SA_result):
        """
        trans the given source code to the target code
        """
        # 将给定的C code 基于rust_depend_context_code翻译成对应的Rust code.
        # rust_depend_context_code =  "\n==========\n".join(["@Source_c_code:\n" + meta['source_c_code_context'].strip() + "\n@Corresponding translated rust code:\n" + meta['trans_rust_code_context'].strip()
        #                                                  for meta in rust_depend_metas])
        rust_depend_context_code =  "\n==========\n".join([meta['trans_rust_code_context'].strip() for meta in rust_depend_metas if meta['trans_rust_code_context'].strip()])
        t_prompt = self.promptSelect.stub_trans(source_c_code.strip(), rust_depend_context_code.strip(), SA_result)

        
        response = self.generator.get_response(t_prompt)
        self._log_prompt_response("Code Stub Trans", t_prompt, response, code_unique_names)
        
        trans_rust_code  = self._extract_stub_code_trans(response)
        
        rust_depend_code = "\n".join([meta['trans_rust_code_context'].strip() for meta in rust_depend_metas])
        # write_rust_code = trans_rust_code
        if len(trans_rust_code) != 0:
            code_diff_prompt = self.promptSelect.code_diff(rust_depend_code + "\n==========\n" + rust_file_code, trans_rust_code)
            code_diff_response = self.generator.get_response(code_diff_prompt)
            write_rust_code = self._extract_code_diff(code_diff_response)
            self._log_prompt_response("Code Diff", code_diff_prompt, code_diff_response, code_unique_names)
        else: write_rust_code = trans_rust_code
        
        trans_rust_code_context = self.rust_parser.extract_item_content(write_rust_code)
        return write_rust_code, "", trans_rust_code_context



    def _trans_rust_path_depend(self, formatted_depend_context, formatted_trans_context,rust_pj_tree_str):
        # A  --> B; A --> C; 当前翻译的是A (formatted_trans_context); 已经翻译的是B, C (formatted_depend_context); 
        # A 是调用方：Caller ; B, C 是被调用方: Callee
        # 现在，为了A 能够访问到 B, C, 需要在 A的文件路径当中，添加B,C的访问
        callee_rust_path = formatted_depend_context
        caller_rust_path = formatted_trans_context
        t_prompt = self.promptSelect.trans_rust_path_depend(rust_pj_tree_str, callee_rust_path, caller_rust_path)
        response = self.generator.get_response(t_prompt)
        self._log_prompt_response("Path Dependency Translation", t_prompt, response)
        trans_rust_path_depend = self._extract_file_depend_trans(response)
        return trans_rust_path_depend
    
    

    def _log_prompt_response(self, prompt_type, prompt, response, code_id = ""):
        with open(self._runLog_path, 'a', encoding='utf-8') as f:
            f.write(f"\n=== {prompt_type} Prompt; code_id: {code_id} ===\n")
            f.write(prompt + "\n")
            f.write(f"\n=== {prompt_type} Response; code_id: {code_id} ===\n")
            f.write(response + "\n")
    
    
    def _extract_pj_tree_map(self, response):
        pj_tree_pattern = r'```\s*project_tree\s*\n(.*?)\n```'
        file_map_pattern = r'```\s*file_map\s*\n(.*?)\n```'
        pj_tree_match = re.search(pj_tree_pattern, response, re.DOTALL)
        file_map_match = re.search(file_map_pattern, response, re.DOTALL)
        
        assert pj_tree_match is not None, "Failed to extract project tree from response"
        assert file_map_match is not None, "Failed to extract file map from response"   
        tree_content = pj_tree_match.group(1).strip()
        file_map_content = file_map_match.group(1).strip()
        
        return tree_content.replace('```', ''), file_map_content.replace('```', '')
    

    def _extract_code_diff(self, response):
        # Extract Rust code
        rust_code = ""
        
        # Try to extract from <rust_code> tags first
        rust_code_pattern = r'<rust_code>\n(.*?)\n</rust_code>'
        rust_match = re.search(rust_code_pattern, response, re.DOTALL)
        if rust_match:
            rust_code = rust_match.group(1).strip()
            
        # Clean up the extracted code
        rust_code = rust_code.replace('```', '').replace("rust\n", "")
        return rust_code 
  
    def _extract_signature(self, response):
        # Extract Rust code
        rust_code = ""
        
        # Try to extract from <rust_code> tags first
        rust_code_pattern = r'<signatures>\n(.*?)\n</signatures>'
        rust_match = re.search(rust_code_pattern, response, re.DOTALL)
        if rust_match:
            rust_code = rust_match.group(1).strip()
            
        # Clean up the extracted code
        rust_code = rust_code.replace('```', '').replace("rust\n", "")
        return rust_code 

    def _extract_stub_code_trans(self,response):

        # Extract Rust code
        rust_code = ""
        
        # Try to extract from <rust_code> tags first
        rust_code_pattern = r'<rust_stubs>\n(.*?)\n</rust_stubs>'
        rust_match = re.search(rust_code_pattern, response, re.DOTALL)
        if rust_match:
            rust_code = rust_match.group(1).strip()
            
        # Clean up the extracted code
        rust_code = rust_code.replace('```', '').replace("rust\n", "")
        return rust_code 
      
        
    def _extract_selected_rust(self, response):
        """
        从响应中提取 Rust 代码和名称。
        <related_item name="...">...</related_item>
        """
        rust_code_list = []
        
        # 提取新格式的代码 <related_item name="...">...</related_item>
        related_pattern = r'<related_item\s+name="([^"]+)">\s*```(?:rust)?\s*(.*?)\s*```\s*</related_item>'
        related_matches = re.finditer(related_pattern, response, re.DOTALL)
        
        for match in related_matches:
            name = match.group(1).strip()
            code = match.group(2).strip()
            
            # 清理代码（移除可能的额外标记）
            code = code.replace('rust\n', '').replace('```', '')
            
            # rust_code_list.append({
            #     'name': name,
            #     'code': code
            # })
            rust_code_list.append(code)
        
        return "\n===\n".join(rust_code_list)


    def _extract_fixed_rust(self, response):
        rust_code_list = []
        code_block_pattern = r'```rust\n(.*?)```'
        code_block_matches = re.finditer(code_block_pattern, response, re.DOTALL)
        
        # 将每个匹配的代码块内容添加到列表中
        for match in code_block_matches:
            code = match.group(1).strip()
            rust_code_list.append(code)
        
        toml_pattern = r'```toml\n(.*?)```'
        toml_match = re.search(toml_pattern, response, re.DOTALL)
        if toml_match: toml_de = toml_match.group(1).replace("[dependencies]","").strip()
        else: toml_de = ""
        return rust_code_list, toml_de
    
    
    
    def _extract_free_judge(self, response, free_Tag=True):
        # Extract Rust code
        source_code = ""
        
        if "free operation only" in response.lower() and free_Tag: return "Free_Function"
        # Try to extract from <rust_code> tags first
        code_pattern = r'<source_c_code>\n(.*?)\n</source_c_code>'
        source_c_match = re.search(code_pattern, response, re.DOTALL)
        if source_c_match:
            source_code = source_c_match.group(1).strip()
        else: return ""
            
        # Clean up the extracted code
        source_code = source_code.replace('```', '').replace("c\n", "")
        cleaned_code = self._remove_c_comments(source_code)
        is_function_sig = self._is_function_signature_only(cleaned_code)
        if is_function_sig and free_Tag: return "Free_Function"
        
        return cleaned_code   
    
    def _extract_code_trans(self, response):
        code_block_pattern = r'```rust\n(.*?)```'
        code_block_match = re.search(code_block_pattern, response, re.DOTALL)
        if code_block_match:
            rust_code = code_block_match.group(1).strip()
            rust_code = rust_code.replace('```', '').replace("rust\n", "")
            toml_pattern = r'```toml\n(.*?)```'
            toml_match = re.search(toml_pattern, response, re.DOTALL)
            if toml_match: toml_de = toml_match.group(1).replace("[dependencies]","").strip()
            else: toml_de = ""
            return rust_code, toml_de
        else: return "", ""
        

        return rust_code, "", 

    def _extract_file_depend_trans(self, response):
        # 使用正则表达式匹配所有<dependency>标签组
        pattern = r'<dependency>\n(.*?)\n</dependency>'
        # pattern = r'```dependency\n(.*?)\n```'
        matches = re.finditer(pattern, response, re.DOTALL)
        
        # 如果没有找到任何依赖，返回None
        if not matches:
            return None
        
        # 存储所有文件依赖关系
        file_depends = {}
        
        # 处理每一组dependency标签
        for match in matches:
            dependency_content = match.group(1).strip()
            
            # 查找路径注释，允许//和path:之间有任意数量的空格
            path_pattern = r'//\s*path:\s*(.*?)(?:\n|$)'
            path_matches = re.finditer(path_pattern, dependency_content)
            
            # 获取所有路径和它们的位置
            paths_and_positions = [(m.group(1).strip(), m.start()) for m in path_matches]
            
            if not paths_and_positions:
                continue
                
            # 处理每个路径及其对应的依赖代码
            for i in range(len(paths_and_positions)):
                current_path = paths_and_positions[i][0]
                start_pos = paths_and_positions[i][1]
                
                # 确定当前依赖代码的结束位置
                if i < len(paths_and_positions) - 1:
                    end_pos = paths_and_positions[i + 1][1]
                    depend_code = dependency_content[start_pos:end_pos]
                else:
                    depend_code = dependency_content[start_pos:]
                
                # 移除路径注释行，获取实际的依赖代码
                depend_code = re.sub(path_pattern, '', depend_code).strip()
                
                # 将依赖代码添加到对应的路径中
                if current_path in file_depends:
                    file_depends[current_path] += '\n' + depend_code
                else:
                    file_depends[current_path] = depend_code
        
        return file_depends

    def _remove_c_comments(self, c_code):
        # 删除多行注释 /* ... */
        code = re.sub(r'/\*.*?\*/', '', c_code, flags=re.DOTALL)
        
        # 删除单行注释 // ...
        lines = code.split('\n')
        cleaned_lines = []
        for line in lines:
            # 找到 // 的位置，删除其后的内容
            comment_pos = line.find('//')
            if comment_pos != -1:
                line = line[:comment_pos]
            cleaned_lines.append(line.rstrip())
        
        return '\n'.join(cleaned_lines)

    def _is_function_signature_only(self, code):
        # 移除多余的空白字符
        code = ' '.join(code.split())
        
        # 检查是否以 ';' 结尾（函数声明）
        # if code.strip().endswith(';'):
        #     return True
        
        # 检查是否有空的函数体 {}
        if code.strip().endswith('{}'):
            return True
        
        # 检查函数体是否为空（只包含空白字符）
        if '{' in code and '}' in code:
            brace_start = code.find('{')
            brace_end = code.rfind('}')
            if brace_start != -1 and brace_end != -1 and brace_start < brace_end:
                function_body = code[brace_start + 1:brace_end].strip()
                return len(function_body) == 0
        
        return False

"""prompt selection"""
class PromptDefine:
    def pj_tree_trans(self, c_pj_tree, project_name):
        t_template = PromptTemplate(template=handcraftPrompt.pj_tree_trans, input_variables=['c_pj_tree', 'project_name'])
        template = t_template.format(c_pj_tree=c_pj_tree, project_name=project_name)
        return template


    def freeJudge(self, source_c_code, called_c_code_context, pointToInfo):
        t_template = PromptTemplate(template=handcraftPrompt.freeJudge, input_variables=['c_code_context','called_c_code_context','pointToInfo'])
        template = t_template.format(source_c_code=source_c_code, called_c_code_context=called_c_code_context, pointToInfo=pointToInfo)
        return template

    def code_trans(self, source_c_code, rust_code_context):
        t_template = PromptTemplate(template=handcraftPrompt.code_trans, input_variables=['source_c_code', 'rust_code_context'])
        template = t_template.format(source_c_code=source_c_code, rust_code_context=rust_code_context)
        return template



    def SA_code_trans(self, source_c_code, rust_code_context, SA_result):
        t_template = PromptTemplate(template=handcraftPrompt.SA_code_trans, input_variables=['source_c_code', 'rust_code_context','SA_result'])
        template = t_template.format(source_c_code=source_c_code, rust_code_context=rust_code_context, SA_result=SA_result)
        return template

    def stub_trans(self, source_c_code, rust_code_context, SA_result):
        t_template = PromptTemplate(template=handcraftPrompt.stub_trans, input_variables=['source_c_code', 'rust_code_context','SA_result'])
        template = t_template.format(source_c_code=source_c_code, rust_code_context=rust_code_context, SA_result=SA_result)
        return template
    
    def rust_error_fix(self, error_description, primary_item, related_item, fix_info):
        t_template = PromptTemplate(template=handcraftPrompt.rust_error_fix, input_variables=['error_description', 'primary_item', 'related_item', 'fix_info'])
        template = t_template.format(error_description=error_description, primary_item=primary_item, related_item=related_item, fix_info=fix_info)
        return template
    
    def typdef_var_replace(self, source_c_code):
        t_template = PromptTemplate(template=handcraftPrompt.typdef_var_replace, input_variables=['source_c_code'])
        template = t_template.format(source_c_code=source_c_code)
        return template
    

    def error_related_code(self, error_log, primary_item, related_items):
        t_template = PromptTemplate(template=handcraftPrompt.error_related_code, input_variables=['error_log', 'primary_item', 'related_items'])
        template = t_template.format(error_log=error_log, primary_item=primary_item, related_items=related_items)
        return template
    
    def trans_rust_path_depend(self, rust_pj_tree, callee_rust_path, caller_rust_path):
        t_template = PromptTemplate(template=handcraftPrompt.trans_rust_path_depend, input_variables=['rust_pj_tree', 'callee_rust_path', 'caller_rust_path'])
        template = t_template.format(rust_pj_tree=rust_pj_tree, callee_rust_path=callee_rust_path, caller_rust_path=caller_rust_path)
        return template
    
    def code_diff(self, file_code, trans_code):
        t_template = PromptTemplate(template=handcraftPrompt.code_diff, input_variables=['file_code', 'trans_code'])
        template = t_template.format(file_code=file_code, trans_code=trans_code)
        return template

    def extract_signatures(self, code):
        t_template = PromptTemplate(template=handcraftPrompt.extract_signatures, input_variables=['code'])
        template = t_template.format(code=code)
        return template
