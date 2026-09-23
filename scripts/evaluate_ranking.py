"""Evaluate real recommendations against human-rated contractor relevance."""
import argparse
import json
import math
from pathlib import Path
from hackalem.catalog import Query
from hackalem.catalog_store import initialize_database, read_profiles
from hackalem.ai_model import MiniLMEncoder
from hackalem.recommender import Recommender

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ratings", type=Path, help="JSON list of query/relevance objects")
    args = parser.parse_args()
    cases = json.loads(args.ratings.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        parser.error("Provide a non-empty list of human-rated cases.")
    initialize_database()
    profiles = read_profiles()
    ids = {p["id"] for p in profiles}
    engine = Recommender(profiles, lambda: MiniLMEncoder(offline=True), None)
    scores = []
    for case in cases:
        query = Query(**case["query"])
        ratings = case["relevance"]
        if not ratings or any(k not in ids or type(v) is not int or v not in range(4) for k, v in ratings.items()):
            parser.error("Relevance must map known contractor IDs to integer grades 0..3.")
        result = engine.recommend(query)
        if any(card["id"] not in ratings for card in result["cards"]):
            parser.error("Rate every returned contractor; missing grades must not silently count as zero.")
        from hackalem.catalog import belongs, rejection_reasons
        eligible = {p["id"] for p in profiles if belongs(p, query) and not rejection_reasons(p, query)}
        if not eligible <= ratings.keys():
            parser.error("Rate all eligible contractors for an unbiased ideal ranking.")
        grades = [ratings[c["id"]] for c in result["cards"]]
        ideal = sorted((ratings[k] for k in eligible), reverse=True)[:3]
        dcg = lambda values: sum((2**g-1)/math.log2(i+2) for i,g in enumerate(values))
        denominator = dcg(ideal)
        if not denominator:
            parser.error("Each case needs at least one relevant eligible contractor.")
        scores.append(dcg(grades)/denominator)
    print(json.dumps({"cases": len(scores), "mean_ndcg_at_3": sum(scores)/len(scores)}, indent=2))

if __name__ == "__main__":
    main()
