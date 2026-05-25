# vLLM Benchmark — Prompt Library
#
# Bu dosya tüm benchmark test promptlarını içerir.
# Her prompt bloğu "## prompt_key" başlığıyla başlar.
# Parametreler YAML-benzeri "key: value" formatındadır.
# Prompt metni "---" ayracından sonra, bir sonraki "##" başlığına kadar devam eder.
#
# Kullanılabilir parametreler:
#   label       : UI'da gösterilen kısa etiket
#   max_tokens  : Maksimum üretilecek token sayısı (varsayılan: 256)
#   temperature : Üretim sıcaklığı, 0.0–2.0 (varsayılan: benchmark ayarından alınır)
#
# Yeni prompt eklemek için:
#   1. "## yeni_key" başlığı ekleyin (boşluk olmadan, küçük harf)
#   2. label, max_tokens parametrelerini yazın
#   3. "---" ayracından sonra prompt metnini yazın
#   4. UI'daki Benchmark → Prompts bölümünden seçin
#
# ⚠ "custom" bloğu özeldir — UI'dan girilecek prompt için yer tutucudur.


## short

label: Short (~50 tok)
max_tokens: 50

---
What is 12/2? Answer in one sentence.


## medium

label: Medium (~512 tok)
max_tokens: 512

---
Explain the difference between TCP and UDP networking protocols. Include key characteristics, use cases, and trade-offs.


## long

label: Long (~2K tok)
max_tokens: 2048

---
Write a comprehensive technical analysis of MoE (Mixture of Experts) architecture in large language models. Cover: what it is, how routing works, why it's efficient, key implementations (Switch Transformer, Mixtral, etc.), training challenges, and inference optimization techniques.


## coding

label: Code (~1K tok)
max_tokens: 1024

---
Write a Python implementation of a binary search tree with insert, search, delete, and in-order traversal methods. Include proper error handling and docstrings.


## code_quality

label: Code Quality (~1K tok)
max_tokens: 1024

---
Review the following Python code for quality issues. Analyze code structure, naming conventions, error handling, performance, and suggest improvements with refactored code:

```python
def proc(d):
    r = []
    for i in range(len(d)):
        if d[i] > 0:
            r.append(d[i] * 2)
        else:
            r.append(0)
    return r

def fetch(url):
    import requests
    r = requests.get(url)
    return r.json()
```


## test_gen

label: Test Gen (~1.5K tok)
max_tokens: 1536

---
Write comprehensive unit tests using pytest for the following Python class. Include edge cases, error cases, and parametrized tests:

```python
class Calculator:
    def __init__(self):
        self.history = []

    def add(self, a, b):
        result = a + b
        self.history.append(('add', a, b, result))
        return result

    def divide(self, a, b):
        if b == 0:
            raise ValueError('Division by zero')
        result = a / b
        self.history.append(('divide', a, b, result))
        return result

    def get_history(self):
        return list(self.history)

    def clear_history(self):
        self.history.clear()
```


## debug

label: Debug (~1K tok)
max_tokens: 1024

---
Debug the following Python code. It should read a CSV file, calculate averages per category, and return sorted results. Identify all bugs, explain each one, and provide the corrected code:

```python
import csv

def analyze_csv(filepath):
    results = {}
    with open(filepath) as f:
        reader = csv.reader(f)
        headers = next(reader)
        for row in reader:
            category = row[0]
            value = row[1]
            if category in results:
                results[category].append(value)
            else:
                results[category] = value
    
    averages = {}
    for cat, vals in results.items():
        averages[cat] = sum(vals) / len(vals)
    
    return sorted(averages, key=lambda x: averages[x])
```


## bug_find

label: Bug Find (~1.5K tok)
max_tokens: 1536

---
Analyze the following Python code for potential bugs, security vulnerabilities, race conditions, and edge cases. List each issue with severity (critical/high/medium/low), explanation, and fix:

```python
import threading
import sqlite3
import os

class UserManager:
    def __init__(self, db_path):
        self.db = sqlite3.connect(db_path)
        self.cache = {}
        self.lock = threading.Lock()

    def get_user(self, user_id):
        if user_id in self.cache:
            return self.cache[user_id]
        cursor = self.db.execute(
            f'SELECT * FROM users WHERE id = {user_id}'
        )
        user = cursor.fetchone()
        self.cache[user_id] = user
        return user

    def delete_user(self, user_id):
        self.db.execute(
            f'DELETE FROM users WHERE id = {user_id}'
        )
        self.db.commit()
        del self.cache[user_id]

    def backup(self, path):
        os.system(f'cp {self.db_path} {path}')
```


## custom

label: Custom
max_tokens: 256

---

