from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision
)
from datasets import Dataset
import pandas as pd
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
import os
from dotenv import load_dotenv

load_dotenv()

class RAGASEvaluator:
    def __init__(self, groq_api_key=None, model_name="llama-3.1-8b-instant"):
        """Initialize RAGAS evaluator with Groq LLM"""
        self.groq_api_key = groq_api_key or os.environ.get("GROQ_API_KEY")
        self.model_name = model_name
        
        # Initialize LLM for evaluation
        self.llm = ChatGroq(
            model=model_name,
            temperature=0,
            groq_api_key=self.groq_api_key
        )
        
        # Initialize embeddings for scoring
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    
    def prepare_test_data(self, question, retrieved_contexts, generated_answer):
        """Prepare data in RAGAS format"""
        return {
            "question": question,
            "contexts": retrieved_contexts,
            "answer": generated_answer,
            "ground_truth": ""
        }
    
    def evaluate_single_query(self, question, retrieved_contexts, generated_answer):
        """Evaluate a single Q&A pair"""
        test_data = self.prepare_test_data(question, retrieved_contexts, generated_answer)
        
        dataset = Dataset.from_dict({
            "question": [test_data["question"]],
            "contexts": [test_data["contexts"]],
            "answer": [test_data["answer"]],
            "ground_truth": [test_data["ground_truth"]]
        })
        
        score = evaluate(
            dataset,
            metrics=[
                faithfulness,
                answer_relevancy,
                context_precision
            ],
            llm=self.llm,
            embeddings=self.embeddings
        )
        
        return score
    
    def evaluate_batch(self, test_cases):
        """Evaluate multiple Q&A pairs"""
        questions = []
        contexts_list = []
        answers = []
        
        for test in test_cases:
            questions.append(test["question"])
            contexts_list.append(test["contexts"])
            answers.append(test["answer"])
        
        dataset = Dataset.from_dict({
            "question": questions,
            "contexts": contexts_list,
            "answer": answers,
            "ground_truth": [""] * len(test_cases)
        })
        
        scores = evaluate(
            dataset,
            metrics=[
                faithfulness,
                answer_relevancy,
                context_precision
            ],
            llm=self.llm,
            embeddings=self.embeddings
        )
        
        return scores.to_pandas()
    
    def generate_report(self, scores_df):
        """Generate a readable evaluation report"""
        report = f"""
        ╔════════════════════════════════════════════╗
        ║         RAGAS EVALUATION REPORT            ║
        ╚════════════════════════════════════════════╝
        
        📊 OVERALL SCORES (Average across all queries):
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        • Faithfulness:      {scores_df['faithfulness'].mean():.3f} ⭐
        • Answer Relevancy:  {scores_df['answer_relevancy'].mean():.3f} ⭐
        • Context Precision: {scores_df['context_precision'].mean():.3f} ⭐
        
        📈 INTERPRETATION:
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        Scores are on a scale of 0-1:
        • 0.8-1.0  → Excellent ✅
        • 0.6-0.8  → Good ⚠️
        • 0.4-0.6  → Fair ⚠️
        • 0.0-0.4  → Poor ❌
        
        🎯 RECOMMENDATIONS:
        """
        
        avg_faithfulness = scores_df['faithfulness'].mean()
        avg_relevancy = scores_df['answer_relevancy'].mean()
        avg_precision = scores_df['context_precision'].mean()
        
        if avg_faithfulness < 0.7:
            report += "\n• ❌ LOW FAITHFULNESS: Model is hallucinating. Consider:"
            report += "\n   - Using a more factual LLM model"
            report += "\n   - Reducing temperature"
            report += "\n   - Adding stricter prompts"
        
        if avg_relevancy < 0.7:
            report += "\n• ❌ LOW ANSWER RELEVANCY: Answers miss the question. Consider:"
            report += "\n   - Improving retrieval quality"
            report += "\n   - Using better question-answer prompting"
        
        if avg_precision < 0.7:
            report += "\n• ❌ LOW CONTEXT PRECISION: Retrieved docs are off-topic. Consider:"
            report += "\n   - Improving embedding model"
            report += "\n   - Adjusting retrieval parameters (k, fetch_k)"
            report += "\n   - Adding metadata filtering"
        
        report += "\n\n" + "="*50 + "\n"
        return report


# Example Usage
if __name__ == "__main__":
    evaluator = RAGASEvaluator()
    
    test_cases = [
        {
            "question": "What storage system does OmniDoc use?",
            "contexts": [
                "OmniDoc AI uses FAISS for vector storage",
                "FAISS is an efficient similarity search library"
            ],
            "answer": "OmniDoc AI uses FAISS for vector storage"
        }
    ]
    
    results = evaluator.evaluate_batch(test_cases)
    report = evaluator.generate_report(results)
    print(report)
    
    results.to_csv("ragas_evaluation_results.csv", index=False)
    print("✅ Results saved to ragas_evaluation_results.csv")