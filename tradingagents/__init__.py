# Load a .env file at package import so every entry point (the runner, the
# API, the jobs) sees the same environment. find_dotenv(usecwd=True) walks
# from the CWD; load_dotenv defaults to override=False, so it never clobbers
# values the caller has already exported.
#
# The LLM pieces that used to sit here (the `.env.enterprise` Azure keys and
# the langchain/langgraph warning filters) went with the AI analysts on
# Oct 02, 2026: "remove the new crypto, analysis and llm models completly,
# i will not use them anymore".
try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
except ImportError:
    pass

