# Best Practices for Prompt Injection Defense in Production AI Systems

## 1. Content Filtering Strategies

### What:
Content filtering is a crucial step in preventing prompt injection attacks by detecting and blocking malicious prompts.

### Why:
Effective content filtering prevents data leakage, unauthorized access, or system compromise by ensuring that only safe inputs are processed by the LLM.

### How:
1. **Install NLTK Library**:
   ```bash
   pip install nltk==3.8.1
   ```

2. **Tokenize and Analyze User Inputs**:
   ```python
   import nltk
   from nltk.tokenize import word_tokenize

   # Ensure you have the necessary NLTK data files
   nltk.download('punkt')

   def filter_prompt(prompt):
       try:
           tokens = word_tokenize(prompt)
           for token in tokens:
               if is_malicious(token):
                   return False  # Block prompt
           return True  # Allow prompt
       except Exception as e:
           print(f"Error during tokenization: {e}")
           return False

   def is_malicious(token):
       # Example of a simple malicious keyword check
       malicious_keywords = ["exec", "eval", "import"]
       if any(keyword in token for keyword in malicious_keywords):
           return True
       return False

   prompt = "This is a safe prompt."
   if filter_prompt(prompt):
       print("Prompt allowed")
   else:
       print("Prompt blocked due to potential injection risk.")
   ```

### Edge Cases and Trade-offs:
- **False Positives**: Simple keyword checks can lead to false positives, blocking legitimate prompts.
- **Complexity**: Advanced filtering techniques may require more computational resources.

## 2. Hierarchical Guardrails

### What:
Hierarchical guardrails involve multiple layers of security measures to ensure that only safe inputs are processed by the LLM.

### Why:
A multi-layered approach reduces the likelihood of successful indirect prompt injection exploits and enhances overall system resilience.

### How:
1. **Install Required Libraries**:
   ```bash
   pip install langchain==0.2.3 guardrails-ai==0.4.5 rebuff==0.1.2
   ```

2. **Implement Hierarchical Guardrails**:
   ```python
   from langchain.models import LLM
   from guardrails import Guard, GuardedModel

   # Define the guardrail rules
   guard = Guard.from_yaml("guard_rules.yaml")

   def process_prompt(prompt):
       try:
           model = LLM()
           guarded_model = GuardedModel(model=model, guard=guard)
           response = guarded_model.generate(prompt)
           return response
       except Exception as e:
           print(f"Error during prompt processing: {e}")
           return None

   prompt = "This is a safe prompt."
   response = process_prompt(prompt)
   if response:
       print("Prompt processed successfully")
   else:
       print("Failed to process prompt due to guardrail violations.")
   ```

### Edge Cases and Trade-offs:
- **Complexity**: Implementing multiple layers of security can increase system complexity.
- **Performance Overhead**: Guardrails may introduce additional latency.

## 3. Output Verification

### What:
Output verification involves checking the model's response for any signs of prompt injection or other malicious behavior.

### Why:
Ensuring that the output is safe and does not contain unintended content helps prevent data leakage and unauthorized actions.

### How:
1. **Install Required Libraries**:
   ```bash
   pip install langchain==0.2.3 guardrails-ai==0.4.5 rebuff==0.1.2
   ```

2. **Implement Output Verification**:
   ```python
   from langchain.models import LLM
   from guardrails import Guard, GuardedModel

   # Define the guardrail rules for output verification
   guard = Guard.from_yaml("output_guard_rules.yaml")

   def verify_output(prompt):
       try:
           model = LLM()
           guarded_model = GuardedModel(model=model, guard=guard)
           response = guarded_model.generate(prompt)
           if is_safe_response(response):
               return True
           else:
               print(f"Output verification failed: {response}")
               return False
       except Exception as e:
           print(f"Error during output verification: {e}")
           return None

   def is_safe_response(response):
       # Example of a simple safety check
       if "sensitive data" in response.lower():
           return False
       return True

   prompt = "This is a safe prompt."
   if verify_output(prompt):
       print("Output verified successfully")
   else:
       print("Failed to verify output due to potential injection risk.")
   ```

### Edge Cases and Trade-offs:
- **False Positives**: Simple checks can lead to false positives, blocking legitimate outputs.
- **Complexity**: Advanced verification techniques may require more computational resources.

## 4. Dynamic Defense Mechanisms

### What:
Dynamic defense mechanisms involve adapting security measures based on the context of the prompt and response.

### Why:
Adaptive defenses help mitigate evolving threats by adjusting security policies in real-time.

### How:
1. **Install Required Libraries**:
   ```bash
   pip install langchain==0.2.3 guardrails-ai==0.4.5 rebuff==0.1.2
   ```

2. **Implement Dynamic Defense Mechanisms**:
   ```python
   from langchain.models import LLM
   from guardrails import Guard, GuardedModel

   # Define the dynamic guardrail rules
   guard = Guard.from_yaml("dynamic_guard_rules.yaml")

   def process_dynamic_prompt(prompt):
       try:
           model = LLM()
           guarded_model = GuardedModel(model=model, guard=guard)
           response = guarded_model.generate(prompt)
           return response
       except Exception as e:
           print(f"Error during dynamic prompt processing: {e}")
           return None

   prompt = "This is a safe prompt."
   response = process_dynamic_prompt(prompt)
   if response:
       print("Prompt processed successfully")
   else:
       print("Failed to process prompt due to guardrail violations.")
   ```

### Edge Cases and Trade-offs:
- **Complexity**: Implementing dynamic defenses can increase system complexity.
- **Performance Overhead**: Real-time adaptation may introduce additional latency.

## 5. Context Window Management

### What:
Context window management involves handling the context of prompts to ensure continuity and prevent injection attacks.

### Why:
Effective context window management helps maintain the integrity of conversations and prevents malicious inputs from disrupting the flow.

### How:
1. **Install Required Libraries**:
   ```bash
   pip install langchain==0.2.3 guardrails-ai==0.4.5 rebuff==0.1.2
   ```

2. **Implement Context Window Management**:
   ```python
   from langchain.models import LLM

   def process_context_window(prompt, context):
       try:
           model = LLM()
           response = model.generate(prompt=prompt, context=context)
           return response
       except Exception as e:
           print(f"Error during context window processing: {e}")
           return None

   prompt = "This is a safe prompt."
   context = ["Previous conversation", "Another previous message"]
   response = process_context_window(prompt, context)
   if response:
       print("Prompt processed successfully")
   else:
       print("Failed to process prompt due to context window issues.")
   ```

### Edge Cases and Trade-offs:
- **Complexity**: Managing context can be complex in multi-turn conversations.
- **Performance Overhead**: Handling large contexts may introduce additional latency.

## 6. Layered Security Approach

### What:
A layered security approach involves implementing multiple layers of defense to reduce the likelihood of successful prompt injection attacks.

### Why:
Layered security enhances overall system resilience by providing redundant protection mechanisms.

### How:
1. **Install Required Libraries**:
   ```bash
   pip install langchain==0.2.3 guardrails-ai==0.4.5 rebuff==0.1.2
   ```

2. **Implement Layered Security Approach**:
   ```python
   from langchain.models import LLM
   from guardrails import Guard, GuardedModel

   # Define the layered guardrail rules
   guard = Guard.from_yaml("layered_guard_rules.yaml")

   def process_layered_prompt(prompt):
       try:
           model = LLM()
           guarded_model = GuardedModel(model=model, guard=guard)
           response = guarded_model.generate(prompt)
           return response
       except Exception as e:
           print(f"Error during layered prompt processing: {e}")
           return None

   prompt = "This is a safe prompt."
   response = process_layered_prompt(prompt)
   if response:
       print("Prompt processed successfully")
   else:
       print("Failed to process prompt due to guardrail violations.")
   ```

### Edge Cases and Trade-offs:
- **Complexity**: Implementing multiple layers of security can increase system complexity.
- **Performance Overhead**: Layered defenses may introduce additional latency.

## 7. Markdown Sanitization

### What:
Markdown sanitization involves cleaning up user-generated content to prevent injection attacks through markdown syntax.

### Why:
Sanitizing markdown ensures that only safe and intended content is processed by the LLM, preventing malicious inputs from causing harm.

### How:
1. **Install Required Libraries**:
   ```bash
   pip install bleach==5.0.1
   ```

2. **Implement Markdown Sanitization**:
   ```python
   import bleach

   def sanitize_markdown(markdown):
       try:
           clean_html = bleach.clean(markdown, tags=[], attributes={}, styles=[], strip=True)
           return clean_html
       except Exception as e:
           print(f"Error during markdown sanitization: {e}")
           return None

   markdown = "This is a **safe** prompt."
   sanitized_markdown = sanitize_markdown(markdown)
   if sanitized_markdown:
       print("Markdown sanitized successfully")
   else:
       print("Failed to sanitize markdown due to potential injection risk.")
   ```

### Edge Cases and Trade-offs:
- **False Positives**: Simple sanitization can lead to false positives, blocking legitimate markdown content.
- **Complexity**: Advanced sanitization techniques may require more computational resources.

## 8. Suspicious URL Redaction

### What:
Suspicious URL redaction involves identifying and removing potentially malicious URLs from user inputs.

### Why:
Removing suspicious URLs helps prevent unauthorized access or data leakage through malicious links.

### How:
1. **Install Required Libraries**:
   ```bash
   pip install urllib3==1.26.15
   ```

2. **Implement Suspicious URL Redaction**:
   ```python
   import re

   def redact_suspicious_urls(prompt):
       try:
           url_pattern = r'http[s]?://(?:[a-zA-Z0-9\-\.]+)(?:/[^\s]*)?'
           urls = re.findall(url_pattern, prompt)
           for url in urls:
               if is_malicious_url(url):
                   prompt = prompt.replace(url, "[REDACTED]")
           return prompt
       except Exception as e:
           print(f"Error during URL redaction: {e}")
           return None

   def is_malicious_url(url):
       # Example of a simple malicious URL check
       suspicious_domains = ["malicious.com", "badactor.net"]
       for domain in suspicious_domains:
           if domain in url:
               return True
       return False

   prompt = "Visit http://safe.com and http://malicious.com"
   redacted_prompt = redact_suspicious_urls(prompt)
   if redacted_prompt:
       print("URLs redacted successfully")
   else:
       print("Failed to redact URLs due to potential injection risk.")
   ```

### Edge Cases and Trade-offs:
- **False Positives**: Simple URL checks can lead to false positives, blocking legitimate URLs.
- **Complexity**: Advanced URL analysis techniques may require more computational resources.

## 9. User Confirmation Framework

### What:
A user confirmation framework involves verifying the intent of a prompt through explicit user confirmation before processing it.

### Why:
User confirmation helps prevent unauthorized actions by ensuring that only intended prompts are processed by the LLM.

### How:
1. **Install Required Libraries**:
   ```bash
   pip install langchain==0.2.3 guardrails-ai==0.4.5 rebuff==0.1.2
   ```

2. **Implement User Confirmation Framework**:
   ```python
   from langchain.models import LLM

   def confirm_prompt(prompt):
       try:
           confirmation = input(f"Confirm prompt: {prompt} (y/n): ")
           if confirmation.lower() == "y":
               return True
           else:
               print("Prompt not confirmed by user.")
               return False
       except Exception as e:
           print(f"Error during user confirmation: {e}")
           return None

   def process_confirmed_prompt(prompt):
       try:
           model = LLM()
           if confirm_prompt(prompt):
               response = model.generate(prompt)
               return response
           else:
               return None
       except Exception as e:
           print(f"Error during confirmed prompt processing: {e}")
           return None

   prompt = "This is a safe prompt."
   response = process_confirmed_prompt(prompt)
   if response:
       print("Prompt processed successfully")
   else:
       print("Failed to process prompt due to user confirmation failure.")
   ```

### Edge Cases and Trade-offs:
- **User Experience**: User confirmation can disrupt the flow of conversations.
- **Complexity**: Implementing a robust confirmation framework may require additional development effort.

## 10. End-User Notifications

### What:
End-user notifications involve informing users about potential prompt injection risks or security measures taken during processing.

### Why:
Informing users helps build trust and transparency, ensuring that they are aware of the security measures in place to protect their data.

### How:
1. **Install Required Libraries**:
   ```bash
   pip install langchain==0.2.3 guardrails-ai==0.4.5 rebuff==0.1.2
   ```

2. **Implement End-User Notifications**:
   ```python
   from langchain.models import LLM

   def notify_user(prompt, response):
       try:
           print(f"Prompt: {prompt}")
           if is_safe_response(response):
               print("Response processed successfully")
           else:
               print("Potential injection risk detected. Response not processed.")
       except Exception as e:
           print(f"Error during user notification: {e}")

   def process_prompt_with_notification(prompt):
       try:
           model = LLM()
           response = model.generate(prompt)
           notify_user(prompt, response)
           return response
       except Exception as e:
           print(f"Error during prompt processing with notification: {e}")
           return None

   prompt = "This is a safe prompt."
   response = process_prompt_with_notification(prompt)
   if response:
       print("Prompt processed successfully")
   else:
       print("Failed to process prompt due to potential injection risk.")
   ```

### Edge Cases and Trade-offs:
- **User Experience**: Frequent notifications can disrupt the user experience.
- **Complexity**: Implementing a robust notification system may require additional development effort.

---

Save this document as `~/Desktop/harness-engineering/eval-prompt-injection.md`.