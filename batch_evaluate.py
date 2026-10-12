import json
from evaluate_ragas import RAGASEvaluator

def load_evaluation_data(filepath="evaluation_log.jsonl"):
    """Load logged Q&A data"""
    test_cases = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                test_cases.append(json.loads(line))
    except FileNotFoundError:
        print(f"No evaluation data found at {filepath}")
    return test_cases

if __name__ == "__main__":
    # Load your logged data
    test_cases = load_evaluation_data()
    
    if not test_cases:
        print("No test cases found. Run your app first to generate data.")
        exit(1)
    
    # Convert to RAGAS format
    formatted_cases = [
        {
            "question": case["question"],
            "contexts": case["contexts"],
            "answer": case["answer"]
        }
        for case in test_cases
    ]
    
    # Evaluate
    evaluator = RAGASEvaluator()
    results = evaluator.evaluate_batch(formatted_cases)
    
    # Generate and print report
    report = evaluator.generate_report(results)
    print(report)
    
    # Save detailed results
    results.to_csv("ragas_results.csv", index=False)
    print(f"✅ Evaluated {len(results)} queries")