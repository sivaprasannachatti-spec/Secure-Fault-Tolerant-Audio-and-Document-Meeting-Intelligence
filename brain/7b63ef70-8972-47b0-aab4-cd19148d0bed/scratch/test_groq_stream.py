import os
import time
from langchain_groq import ChatGroq
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

os.environ["GROQ_API_KEY"] = "gsk_7j65V9VlZl5kFf5l7l7l" # Placeholder, actual will be from env

def test_streaming():
    llm = ChatGroq(
        model="qwen-qwq-32b", # The user is using qwen/qwen3-32b which might be an alias or specific to their setup
        api_key=os.environ.get("GROQ_API_KEY"),
        temperature=0.6,
    )
    
    prompt = ChatPromptTemplate.from_template("Tell me a long story about {topic}")
    chain = prompt | llm | StrOutputParser()
    
    print("Starting stream...")
    start = time.monotonic()
    first_token = True
    for chunk in chain.stream({"topic": "a space adventure"}):
        if first_token:
            print(f"First token received in {time.monotonic() - start:.2f}s")
            first_token = False
        print(chunk, end="", flush=True)
    print("\nStream finished.")

if __name__ == "__main__":
    test_streaming()
