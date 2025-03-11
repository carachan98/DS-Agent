""" This file contains the code for calling all LLM APIs. """

import os
from functools import partial
import tiktoken
from .schema import TooLongPromptError, LLMError

enc = tiktoken.get_encoding("cl100k_base")
STATISTICAL_DIR = None
FINETUNE_STEP = 0

try:
    from helm.common.authentication import Authentication
    from helm.common.request import Request, RequestResult
    from helm.proxy.accounts import Account
    from helm.proxy.services.remote_service import RemoteService
    # setup CRFM API
    auth = Authentication(api_key=open("crfm_api_key.txt").read().strip())
    service = RemoteService("https://crfm-models.stanford.edu")
    account: Account = service.get_account(auth)
except Exception as e:
    print(e)
    print("Could not load CRFM API key crfm_api_key.txt.")

try:   
    import anthropic
    # setup anthropic API key
    anthropic_client = anthropic.Anthropic(api_key=open("claude_api_key.txt").read().strip())
except Exception as e:
    print(e)
    print("Could not load anthropic API key claude_api_key.txt.")
    
try:
    # import openai
    # setup OpenAI API key
    # openai.api_key = 
    from openai import OpenAI
    os.environ["OPENAI_API_KEY"] = "sk-***"
    os.environ["OPENAI_BASE_URL"] = "https://api.yesapikey.com/v1"
    # from openai import OpenAI
    client = OpenAI()
except Exception as e:
    print(e)
    print("Could not load OpenAI API key openai_api_key.txt.")


def log_to_file(log_file, prompt, completion, model, max_tokens_to_sample):
    """ Log the prompt and completion to a file."""
    with open(log_file, "a") as f:
        f.write("\n===================prompt=====================\n")
        f.write(f"{anthropic.HUMAN_PROMPT} {prompt} {anthropic.AI_PROMPT}")
        num_prompt_tokens = len(enc.encode(f"{anthropic.HUMAN_PROMPT} {prompt} {anthropic.AI_PROMPT}"))
        f.write(f"\n==================={model} response ({max_tokens_to_sample})=====================\n")
        f.write(completion)
        num_sample_tokens = len(enc.encode(completion))
        f.write("\n===================tokens=====================\n")
        f.write(f"Number of prompt tokens: {num_prompt_tokens}\n")
        f.write(f"Number of sampled tokens: {num_sample_tokens}\n")
        f.write("\n\n")
    
    # Logging for finetuning
    finetune_directory = os.path.join(STATISTICAL_DIR, "finetune_log")
    if not os.path.exists(finetune_directory):
        os.mkdir(finetune_directory)
    global FINETUNE_STEP
    FINETUNE_STEP += 1
    with open(os.path.join(finetune_directory, f"step_{FINETUNE_STEP}.txt"), "wt") as f:
        f.write(prompt)
        f.write("\n[This is a split string for finetuning]\n")
        f.write(completion)


def complete_text_claude(prompt, stop_sequences=[anthropic.HUMAN_PROMPT], model="claude-v1", max_tokens_to_sample = 2000, temperature=0.5, log_file=None, **kwargs):
    """ Call the Claude API to complete a prompt."""

    ai_prompt = anthropic.AI_PROMPT
    if "ai_prompt" in kwargs is not None:
        ai_prompt = kwargs["ai_prompt"]

    try:
        rsp = anthropic_client.completions.create(
            prompt=f"{anthropic.HUMAN_PROMPT} {prompt} {ai_prompt}",
            stop_sequences=stop_sequences,
            model=model,
            temperature=temperature,
            max_tokens_to_sample=max_tokens_to_sample,
            **kwargs
        )
    except anthropic.APIStatusError as e:
        print(e)
        raise TooLongPromptError()
    except Exception as e:
        raise LLMError(e)

    completion = rsp.completion
    if log_file is not None:
        log_to_file(log_file, prompt, completion, model, max_tokens_to_sample)
    return completion


def get_embedding_crfm(text, model="openai/gpt-4-0314"):
    request = Request(model="openai/text-similarity-ada-001", prompt=text, embedding=True)
    request_result: RequestResult = service.make_request(auth, request)
    return request_result.embedding 
    
def complete_text_crfm(prompt=None, stop_sequences = None, model="openai/gpt-4-0314",  max_tokens_to_sample=2000, temperature = 0.5, log_file=None, messages = None, **kwargs):
    
    random = log_file
    if messages:
        request = Request(
                prompt=prompt, 
                messages=messages,
                model=model, 
                stop_sequences=stop_sequences,
                temperature = temperature,
                max_tokens = max_tokens_to_sample,
                random = random
            )
    else:
        print("model", model)
        print("max_tokens", max_tokens_to_sample)
        request = Request(
                prompt=prompt, 
                model=model, 
                stop_sequences=stop_sequences,
                temperature = temperature,
                max_tokens = max_tokens_to_sample,
                random = random
        )
    
    try:      
        request_result: RequestResult = service.make_request(auth, request)
    except Exception as e:
        # probably too long prompt
        print(e)
        raise TooLongPromptError()
    
    if request_result.success == False:
        print(request.error)
        raise LLMError(request.error)
    completion = request_result.completions[0].text
    if log_file is not None:
        log_to_file(log_file, prompt, completion, model, max_tokens_to_sample)
    return completion


def complete_text_openai(prompt, stop_sequences=[], model="gpt-3.5-turbo", max_tokens_to_sample=1000, temperature=0.5, log_file=None, **kwargs):
    """ Call the OpenAI API to complete a prompt."""
    raw_request = {
          "model": model,
        #   "prompt":prompt,
        #   "role":"user",
        #   "temperature": temperature,
        #   "max_tokens": max_tokens_to_sample,
          "stop": stop_sequences or None,  # API doesn't like empty list
          **kwargs
    }
    
    iteration = 0
    completion = None
    while iteration < 10:
        try:
            if model.startswith("gpt-3.5") or model.startswith("gpt-4"):
                # messages = [{"role": "user", "content": prompt}]
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ]
                # TODO migrate old version to new openai api
                # response = openai.ChatCompletion.create(**{"messages": messages,**raw_request})
                # completion = response["choices"][0]["message"]["content"]
                response = client.chat.completions.create(**{"messages": messages,**raw_request})
                completion = response.choices[0].message.content
                print(completion)
            else:
                response = openai.Completion.create(**{"prompt": prompt,**raw_request})
                completion = response["choices"][0]["text"]
            break
        except Exception as e:
            iteration += 1
            print(f"===== Retry: {iteration} =====")
            print(f"Error occurs when calling API: {e}")
            continue
    
    ## Count consumed tokens.
    if STATISTICAL_DIR:
        statitical_file = STATISTICAL_DIR + "/count_tokens.txt"
        try:
            with open(statitical_file, 'r') as file:
                current_token_count = int(file.read().strip())
        except FileNotFoundError:
            current_token_count = 0
        num_prompt_tokens = len(enc.encode(f"{anthropic.HUMAN_PROMPT} {prompt} {anthropic.AI_PROMPT}"))
        num_sample_tokens = len(enc.encode(completion))     
        total_token_count = current_token_count + num_prompt_tokens + num_sample_tokens
        with open(statitical_file, 'w') as file:
            file.write(str(total_token_count))
    
    if log_file is not None:
        log_to_file(log_file, prompt, completion, model, max_tokens_to_sample)
    return completion

def complete_text(prompt, log_file, model, **kwargs):
    """ Complete text using the specified model with appropriate API. """
    
    if model.startswith("claude"):
        # use anthropic API
        completion = complete_text_claude(prompt, stop_sequences=[anthropic.HUMAN_PROMPT, "Observation:"], log_file=log_file, model=model, **kwargs)
    elif "/" in model:
        # use CRFM API since this specifies organization like "openai/..."
        completion = complete_text_crfm(prompt, stop_sequences=["Observation:"], log_file=log_file, model=model, **kwargs)
    else:
        # use OpenAI API
        completion = complete_text_openai(prompt, stop_sequences=["Observation:"], log_file=log_file, model=model, **kwargs)
    return completion

# specify fast models for summarization etc
FAST_MODEL = "claude-v1"
def complete_text_fast(prompt, **kwargs):
    return complete_text(prompt = prompt, model = FAST_MODEL, temperature =0.01, **kwargs)
# complete_text_fast = partial(complete_text_openai, temperature= 0.01)

