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
        
        self.conversation_history = []
        
        if "gpt" in self.model_name:
            
            OPENAI_API_KEY = "Set_Your_OpenAI_API_KEY"
            openai.api_key = OPENAI_API_KEY
            openai.api_base = "https://openkey.cloud/v1"

        else:
            self.model_name_or_path = args.model_path
            self.model = self.model_load()
    
    def model_load(self):
        self.model = AutoModelForCausalLM.from_pretrained(self.model_name_or_path,torch_dtype=torch.float16, low_cpu_mem_usage=True).to('cuda')
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name_or_path)

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


        response = chat_completion_with_backoff(
            model=self.model_name,
            messages=messages,
            temperature=0.1,
            max_tokens = 5214,
            n=num_results
        )
        if num_results == 1:
            return response.choices[0]['message']['content']
        else:  
            return [choice['message']['content'] for choice in response.choices]
            
        

    def get_token_count(self, query):
        if "gpt" in self.model_name:
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
            return -1