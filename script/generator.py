import json
from datetime import datetime
import os
import time
import requests
import torch
from itertools import cycle
import handcraftPrompt
import pandas as pd
import subprocess
import openai
from transformers import LlamaForCausalLM,LlamaTokenizer,AutoModel, AutoModelForCausalLM,AutoTokenizer
import transformers
import tiktoken  
"""initial model generator"""
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type
)  # for exponential backoff

@retry(
    retry=retry_if_exception_type((openai.error.APIError, openai.error.APIConnectionError, openai.error.RateLimitError, openai.error.ServiceUnavailableError, openai.error.Timeout)), 
    wait=wait_random_exponential(multiplier=1, max=60), 
    stop=stop_after_attempt(10)
)

def chat_completion_with_backoff(**kwargs):
    return openai.ChatCompletion.create(**kwargs)

class Generator:
    def __init__(self, args):
        self.args = args
        self.model_name = self.args.model_name
        self.is_openai_model = "gpt" in self.model_name.lower()
        
        self.conversation_history = []
        
        if self.is_openai_model:
            
            OPENAI_API_KEY = "Set_Your_OpenAI_API_KEY"
            openai.api_key = OPENAI_API_KEY
            openai.api_base = "https://openkey.cloud/v1"

        else:
            self.model_name_or_path = args.model_path
            if not self.model_name_or_path:
                raise ValueError("--model_path is required when --model_name is not a GPT/OpenAI model")
            self.model = self.model_load()
    
    def model_load(self):
        dtype_name = getattr(self.args, "local_dtype", "auto")
        dtype_map = {
            "auto": "auto",
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        torch_dtype = dtype_map.get(dtype_name)
        if torch_dtype is None:
            raise ValueError(f"Unsupported --local_dtype: {dtype_name}")

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name_or_path,
            trust_remote_code=getattr(self.args, "trust_remote_code", False),
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name_or_path,
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=True,
            device_map=getattr(self.args, "device_map", "auto"),
            trust_remote_code=getattr(self.args, "trust_remote_code", False),
        )
        self.model.eval()

        if self.tokenizer.pad_token_id is None and self.tokenizer.eos_token_id is not None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        return self.model

    def reset_history(self):
        self.conversation_history = []
        return True       

    def get_history(self):
        return self.conversation_history
  
    def get_response(self,query, use_history=True, num_results=1)->str:
        messages = [
                {"role":"system", "content":handcraftPrompt.sys_prompt},
                {"role":"user","content":query}
            ]

        if not self.is_openai_model:
            return self._get_local_response(messages, num_results=num_results)

        response = chat_completion_with_backoff(
            model=self.model_name,
            messages=messages,
            temperature=getattr(self.args, "temperature", 0.1),
            max_tokens=getattr(self.args, "max_new_tokens", 5214),
            n=num_results
        )
        if num_results == 1:
            return response.choices[0]['message']['content']
        else:  
            return [choice['message']['content'] for choice in response.choices]
            
    def _get_local_response(self, messages, num_results=1):
        if hasattr(self.tokenizer, "apply_chat_template") and self.tokenizer.chat_template is not None:
            prompt = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        else:
            prompt = (
                f"System:\n{messages[0]['content']}\n\n"
                f"User:\n{messages[1]['content']}\n\n"
                "Assistant:\n"
            )

        inputs = self.tokenizer(prompt, return_tensors="pt")
        input_device = next(self.model.parameters()).device
        inputs = {key: value.to(input_device) for key, value in inputs.items()}
        input_token_count = inputs["input_ids"].shape[-1]

        generation_kwargs = {
            **inputs,
            "max_new_tokens": getattr(self.args, "max_new_tokens", 5214),
            "temperature": getattr(self.args, "temperature", 0.1),
            "do_sample": getattr(self.args, "temperature", 0.1) > 0,
            "num_return_sequences": num_results,
            "pad_token_id": self.tokenizer.pad_token_id,
            "eos_token_id": self.tokenizer.eos_token_id,
        }

        print("Local generation start...", flush=True)
        with torch.inference_mode():
            outputs = self.model.generate(**generation_kwargs)
        print("Local generation done.", flush=True)

        responses = [
            self.tokenizer.decode(output[input_token_count:], skip_special_tokens=True).strip()
            for output in outputs
        ]
        return responses[0] if num_results == 1 else responses
        

    def get_token_count(self, query):
        if self.is_openai_model:
            try:
                if "gpt-4" in self.model_name:
                    encoding = tiktoken.encoding_for_model("gpt-4")
                elif "gpt-3.5" in self.model_name:
                    encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
                else:
                    encoding = tiktoken.get_encoding("cl100k_base")
                
                tokens = encoding.encode(query)
                return len(tokens)
            except Exception as e:
                print(f"Error calculating token count: {e}")
                return -1
        else:
            return len(self.tokenizer.encode(query))
