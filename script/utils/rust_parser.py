import os
from tree_sitter import Language, Parser

class RustParser:

    def __init__(self, root_path: str) -> None:
        self.root_path = root_path
        self.rust_parser_so_path = os.path.join(root_path, "dependencyLib/rust_parser.so")

    def get_rust_definitions(self, rust_code: str) -> list:


        RUST_LANGUAGE = Language(self.rust_parser_so_path, 'rust') # 注意：路径可能需要配置
        parser = Parser()
        parser.set_language(RUST_LANGUAGE)

        tree = parser.parse(bytes(rust_code, "utf8"))
        root_node = tree.root_node

        struct_names = []
        function_names = []
        static_names = []
        type_names = []
        enum_names = []
        const_names = []
        impl_functions = []  
        impl_names = []

        struct_query = RUST_LANGUAGE.query("""
        (struct_item
        name: (type_identifier) @struct_name)
        """)

        function_query = RUST_LANGUAGE.query("""
        (function_item
        name: (identifier) @function_name)
        """)

        static_query = RUST_LANGUAGE.query("""
        (static_item
        name: (identifier) @static_name)
        """)

        type_query = RUST_LANGUAGE.query("""
        (type_item
        name: (type_identifier) @type_name)
        """)

        enum_query = RUST_LANGUAGE.query("""
        (enum_item
        name: (type_identifier) @enum_name)
        """)

        const_query = RUST_LANGUAGE.query("""
        (const_item
        name: (identifier) @const_name)
        """)
        

        all_impl_query = RUST_LANGUAGE.query("""
        (impl_item) @impl_item
        """)
        


        struct_captures = struct_query.captures(root_node)
        for node, _ in struct_captures:
            struct_names.append(node.text.decode('utf8'))

        function_captures = function_query.captures(root_node)
        for node, _ in function_captures:

            if not self._is_in_impl_block(node):
                function_names.append(node.text.decode('utf8'))

        static_captures = static_query.captures(root_node)
        for node, _ in static_captures:
            static_names.append(node.text.decode('utf8'))

        type_captures = type_query.captures(root_node)
        for node, _ in type_captures:
            type_names.append(node.text.decode('utf8'))
            
        enum_captures = enum_query.captures(root_node)
        for node, _ in enum_captures:
            enum_names.append(node.text.decode('utf8'))
            
        const_captures = const_query.captures(root_node)
        for node, _ in const_captures:
            const_names.append(node.text.decode('utf8'))

        all_impl_captures = all_impl_query.captures(root_node)
        for node, _ in all_impl_captures:
            type_node = node.child_by_field_name('type')
            trait_node = node.child_by_field_name('trait')
            
            if trait_node and type_node:
                name = f"{trait_node.text.decode('utf8')} for {type_node.text.decode('utf8')}"
                impl_names.append(name)
            elif type_node:
                name = type_node.text.decode('utf8')
                impl_names.append(name)
            else:
                name = "[Anonymous impl]"
                impl_names.append(name)



        all_names = struct_names + function_names + static_names + type_names + enum_names + impl_names + const_names
        return all_names
        
    def _is_in_impl_block(self, node):

        current = node
        while current.parent is not None:
            current = current.parent
            if current.type == 'impl_item':
                return True
        return False

    def _get_impl_type_name(self, node):

        current = node
        while current.parent is not None:
            current = current.parent
            if current.type == 'impl_item':
                type_node = current.child_by_field_name('type')
                if type_node:
                    return type_node.text.decode('utf8')
                break
        return None

    def find_rust_items(self, code_string: str) -> list[dict]:

        
        RUST_LANGUAGE = Language(self.rust_parser_so_path, 'rust') 
        parser = Parser()
        parser.set_language(RUST_LANGUAGE)
        
        items = []
        code_bytes = bytes(code_string, "utf8")
        tree = parser.parse(code_bytes)
        root_node = tree.root_node
        query_string = """
        [
        (function_item) @item
        (struct_item) @item
        (enum_item) @item
        (impl_item) @item
        (trait_item) @item
        (type_item) @item
        (const_item) @item
        (static_item) @item
        (use_declaration) @item
        (mod_item) @item
        ]
        """
        query = RUST_LANGUAGE.query(query_string)
        captures = query.captures(root_node)

        for node, _ in captures:
            start_node = node
            current_node = node
            while current_node.prev_sibling is not None:
                prev_sibling = current_node.prev_sibling
                if prev_sibling.type in ['attribute_item', 'line_comment', 'block_comment']:
                    start_node = prev_sibling
                    current_node = prev_sibling
                else:
                    break
            
            start_line = start_node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            
            item_type = node.type
            name = "[N/A]"

            if item_type == 'function_item':
                name_node = node.child_by_field_name('name')
                if name_node:
                    func_name = name_node.text.decode('utf8')
                    if self._is_in_impl_block(node):
                        
                        impl_type_name = self._get_impl_type_name(node)
                        if impl_type_name:
                            continue
                        else:
                            name = func_name
                    else:
                        name = func_name
                else:
                    name = "[N/A]"
            elif item_type in ['struct_item', 'enum_item', 'trait_item', 'mod_item', 'const_item', 'static_item', 'type_item']:
                name_node = node.child_by_field_name('name')
                if name_node:
                    name = name_node.text.decode('utf8')
            
            elif item_type == 'impl_item':
                type_node = node.child_by_field_name('type')
                trait_node = node.child_by_field_name('trait')
                if trait_node and type_node:
                    name = f"{trait_node.text.decode('utf8')} for {type_node.text.decode('utf8')}"
                elif type_node:
                    name = type_node.text.decode('utf8')
                else:
                    name = "[Anonymous impl]"

            elif item_type == 'use_declaration':
                path_node = node.children[1]
                if path_node:
                    name = path_node.text.decode('utf8')

            items.append({
                "type": item_type.replace('_item', ''),
                "name": name,
                "start_line": start_line,
                "end_line": end_line,
            })
            
        return items



    def extract_item_content(self, code_string: str) -> list[dict]:
        RUST_LANGUAGE = Language(self.rust_parser_so_path, 'rust') 
        parser = Parser()
        parser.set_language(RUST_LANGUAGE)
        
        items = []
        code_bytes = bytes(code_string, "utf8")
        tree = parser.parse(code_bytes)
        root_node = tree.root_node

        query_string = """
        [
        (function_item) @item
        (struct_item) @item
        (enum_item) @item
        (impl_item) @item
        (trait_item) @item
        (mod_item) @item
        ]
        """
        query = RUST_LANGUAGE.query(query_string)
        captures = query.captures(root_node)

        for node, _ in captures:
            item_type = node.type.replace('_item', '')
            content = ""


            if item_type == 'function':
                body_node = node.child_by_field_name('body')
                
                if body_node:
                    signature_end_byte = body_node.start_byte
                    signature_bytes = code_bytes[node.start_byte:signature_end_byte]
                    content = signature_bytes.decode('utf-8').strip()
                else:
                    content = node.text.decode('utf-8')

            elif item_type in ['struct', 'enum', 'trait', 'mod', 'impl']:
                content = node.text.decode('utf-8')
                
            else:
                content = node.text.decode('utf-8')

            name_node = node.child_by_field_name('name')
            name = name_node.text.decode('utf8') if name_node else f"[{item_type}]"
            if item_type == 'impl':
                type_node = node.child_by_field_name('type')
                trait_node = node.child_by_field_name('trait')
                if trait_node and type_node:
                    name = f"impl {trait_node.text.decode('utf8')} for {type_node.text.decode('utf8')}"
                elif type_node:
                    name = f"impl {type_node.text.decode('utf8')}"
            items.append(content)
        return_str = "\n".join(items)
        if len(return_str) == 0:
            return_str = code_string  
        return return_str



    def separate_use_statements(self, rust_code: str) -> tuple[list[str], str]:
        RUST_LANGUAGE = Language(self.rust_parser_so_path, 'rust')
        parser = Parser()
        parser.set_language(RUST_LANGUAGE)

        code_bytes = bytes(rust_code, "utf8")
        tree = parser.parse(code_bytes)
        root_node = tree.root_node
        
        use_query = RUST_LANGUAGE.query("""
        (use_declaration) @use_decl
        """)
        
        use_captures = use_query.captures(root_node)
        use_ranges = []
        use_statements = []
        
        for node, _ in use_captures:
            start_byte = node.start_byte
            end_byte = node.end_byte
            
            use_text = code_bytes[start_byte:end_byte].decode('utf8')
            use_statements.append(use_text)
            
            use_ranges.append((start_byte, end_byte))
        
        use_ranges.sort(key=lambda x: x[0], reverse=True)
        
        remaining_code_bytes = bytearray(code_bytes)
        for start_byte, end_byte in use_ranges:
            use_length = end_byte - start_byte
            remaining_code_bytes[start_byte:end_byte] = b' ' * use_length
        
        remaining_code = remaining_code_bytes.decode('utf8')
        
        lines = remaining_code.split('\n')
        cleaned_lines = []
        prev_empty = False
        
        for line in lines:
            is_empty = not line.strip()
            if is_empty and prev_empty:
                continue  
            cleaned_lines.append(line)
            prev_empty = is_empty
        
        remaining_code = '\n'.join(cleaned_lines).strip()
        
        return use_statements, remaining_code

    def separate_use_statements_with_lines(self, rust_code: str) -> tuple[list[str], list[str]]:
        use_statements, remaining_code = self.separate_use_statements(rust_code)
        
        use_lines = []
        for use_stmt in use_statements:
            use_lines.extend(use_stmt.split('\n'))
        
        code_lines = [line for line in remaining_code.split('\n') if line.strip()]
        
        return use_lines, code_lines
    
    
if __name__ == "__main__":
    pass