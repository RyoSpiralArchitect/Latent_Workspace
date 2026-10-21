# V22 latent-route failures — complete exposed diagnostic panel

All 13 previously incorrect latent-route answers, unchanged. The listed token fork is a token-level event, not an independent semantic judgement. FP32 scores are diagnostic only; no new continuation was generated.

## wb01-event_order-test-0006/s0/absent

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": false,
        "text": "Not specified (since the given memory facts do not provide a relationship between the two events to determine their order)."
      },
      "latent": {
        "exact_match": false,
        "text": "Not specified (since the given memory facts do not provide a relationship between the two events to determine their order)."
      }
    },
    "v22": {
      "inline": {
        "exact_match": false,
        "text": "Nbwxsmihfd."
      },
      "latent": {
        "exact_match": false,
        "text": "Nbwxsmihfd."
      }
    }
  },
  "family": "event_order",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 22.101390838623047,
      "gold_logprob": -0.7270684838294983,
      "gold_margin": -0.06637954711914062,
      "gold_rank": 2,
      "target": 3048,
      "top1": 1186,
      "top_logit": 22.167770385742188,
      "top_ties": 1
    },
    "gold_probability": 0.49990869306984753,
    "gold_token": "Not",
    "gold_token_id": 3048,
    "index": 0,
    "native": {
      "correct": false,
      "gold_logit": 22.125,
      "gold_logprob": -0.6933298110961914,
      "gold_margin": 0.0,
      "gold_rank": 1,
      "target": 3048,
      "top1": 1186,
      "top_logit": 22.125,
      "top_ties": 2
    },
    "recorded_token": "N",
    "recorded_token_id": 1186,
    "teacher_fork_nll_fraction": 0.9705903163802624,
    "teacher_gold_probability": 0.49990624973165276
  },
  "id": "wb01-event_order-test-0006/s0/absent",
  "literal_matches_query_fields": [
    "left"
  ],
  "literal_matches_visible_fact_entity": false,
  "mean_teacher_nll": 0.17858582735061646,
  "memory": "",
  "mode": "absent",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nbwxsmihfd or Nopqjltbgi?",
  "query_spec": {
    "left": "Nbwxsmihfd",
    "op": "earlier",
    "right": "Nopqjltbgi"
  },
  "recorded_text": "Nbwxsmihfd.",
  "split": "test",
  "target": "Not specified."
}
```

## wb01-event_order-test-0006/s1/affected

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": true,
        "text": "Nopqjltbgi"
      },
      "latent": {
        "exact_match": false,
        "text": "Nbwxsmihfd occurs earlier. (Day 17 < Day 6)"
      }
    },
    "v22": {
      "inline": {
        "exact_match": true,
        "text": "Nopqjltbgi."
      },
      "latent": {
        "exact_match": false,
        "text": "Nbwxsmihfd."
      }
    }
  },
  "family": "event_order",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 22.152727127075195,
      "gold_logprob": -2.1189963817596436,
      "gold_margin": -1.9905986785888672,
      "gold_rank": 2,
      "target": 1178,
      "top1": 29494,
      "top_logit": 24.143325805664062,
      "top_ties": 1
    },
    "gold_probability": 0.11916128417868663,
    "gold_token": "op",
    "gold_token_id": 1178,
    "index": 1,
    "native": {
      "correct": false,
      "gold_logit": 22.125,
      "gold_logprob": -2.127277374267578,
      "gold_margin": -2.0,
      "gold_rank": 2,
      "target": 1178,
      "top1": 29494,
      "top_logit": 24.125,
      "top_ties": 1
    },
    "recorded_token": "b",
    "recorded_token_id": 29494,
    "teacher_fork_nll_fraction": 0.9817118288864289,
    "teacher_gold_probability": 0.11916284675345482
  },
  "id": "wb01-event_order-test-0006/s1/affected",
  "literal_matches_query_fields": [
    "left"
  ],
  "literal_matches_visible_fact_entity": true,
  "mean_teacher_nll": 0.24076586299472386,
  "memory": "Event Nbwxsmihfd occurs on day 17.\nEvent Nopqjltbgi occurs on day 6.\nEvent Nmmkxozbif occurs on day 21.\nEvent Nayerhmvgg occurs on day 28.",
  "mode": "affected",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nbwxsmihfd or Nopqjltbgi?",
  "query_spec": {
    "left": "Nbwxsmihfd",
    "op": "earlier",
    "right": "Nopqjltbgi"
  },
  "recorded_text": "Nbwxsmihfd.",
  "split": "test",
  "target": "Nopqjltbgi."
}
```

## wb01-event_order-test-0015/s0/absent

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": true,
        "text": "Not specified"
      },
      "latent": {
        "exact_match": true,
        "text": "Not specified"
      }
    },
    "v22": {
      "inline": {
        "exact_match": false,
        "text": "Nfzyxfrnok."
      },
      "latent": {
        "exact_match": false,
        "text": "Nfzyxfrnok."
      }
    }
  },
  "family": "event_order",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 21.73712158203125,
      "gold_logprob": -0.8634076714515686,
      "gold_margin": -0.2795429229736328,
      "gold_rank": 2,
      "target": 3048,
      "top1": 1186,
      "top_logit": 22.016664505004883,
      "top_ties": 1
    },
    "gold_probability": 0.42838581444546103,
    "gold_token": "Not",
    "gold_token_id": 3048,
    "index": 0,
    "native": {
      "correct": false,
      "gold_logit": 21.75,
      "gold_logprob": -0.8477310538291931,
      "gold_margin": -0.25,
      "gold_rank": 2,
      "target": 3048,
      "top1": 1186,
      "top_logit": 22.0,
      "top_ties": 1
    },
    "recorded_token": "N",
    "recorded_token_id": 1186,
    "teacher_fork_nll_fraction": 0.9757330487423915,
    "teacher_gold_probability": 0.4294621878329792
  },
  "id": "wb01-event_order-test-0015/s0/absent",
  "literal_matches_query_fields": [
    "left"
  ],
  "literal_matches_visible_fact_entity": false,
  "mean_teacher_nll": 0.21656066179275513,
  "memory": "",
  "mode": "absent",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nfzyxfrnok or Nuakqvsbho?",
  "query_spec": {
    "left": "Nfzyxfrnok",
    "op": "earlier",
    "right": "Nuakqvsbho"
  },
  "recorded_text": "Nfzyxfrnok.",
  "split": "test",
  "target": "Not specified."
}
```

## wb01-event_order-test-0015/s0/unaffected

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": true,
        "text": "Nuncjizqah"
      },
      "latent": {
        "exact_match": false,
        "text": "Nenbohyoid"
      }
    },
    "v22": {
      "inline": {
        "exact_match": true,
        "text": "Nuncjizqah."
      },
      "latent": {
        "exact_match": false,
        "text": "Nenbohyoid."
      }
    }
  },
  "family": "event_order",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 17.502199172973633,
      "gold_logprob": -2.7274928092956543,
      "gold_margin": -2.6314640045166016,
      "gold_rank": 2,
      "target": 11242,
      "top1": 1037,
      "top_logit": 20.133663177490234,
      "top_ties": 1
    },
    "gold_probability": 0.06575971414325528,
    "gold_token": "unc",
    "gold_token_id": 11242,
    "index": 1,
    "native": {
      "correct": false,
      "gold_logit": 17.5,
      "gold_logprob": -2.721747875213623,
      "gold_margin": -2.625,
      "gold_rank": 2,
      "target": 11242,
      "top1": 1037,
      "top_logit": 20.125,
      "top_ties": 1
    },
    "recorded_token": "en",
    "recorded_token_id": 1037,
    "teacher_fork_nll_fraction": 0.9964021621387805,
    "teacher_gold_probability": 0.0656106882008741
  },
  "id": "wb01-event_order-test-0015/s0/unaffected",
  "literal_matches_query_fields": [
    "right"
  ],
  "literal_matches_visible_fact_entity": true,
  "mean_teacher_nll": 0.34173157811164856,
  "memory": "Event Nenbohyoid occurs on day 27.\nEvent Nfzyxfrnok occurs on day 8.\nEvent Nuncjizqah occurs on day 17.\nEvent Nuakqvsbho occurs on day 10.",
  "mode": "unaffected",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nuncjizqah or Nenbohyoid?",
  "query_spec": {
    "left": "Nuncjizqah",
    "op": "earlier",
    "right": "Nenbohyoid"
  },
  "recorded_text": "Nenbohyoid.",
  "split": "test",
  "target": "Nuncjizqah."
}
```

## wb01-event_order-test-0015/s1/affected

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": false,
        "text": "Nfzyxfrnok"
      },
      "latent": {
        "exact_match": false,
        "text": "Nfzyxfrnok occurs earlier. (Day 10 < Day 8)"
      }
    },
    "v22": {
      "inline": {
        "exact_match": false,
        "text": "Nfzyxfrnok."
      },
      "latent": {
        "exact_match": false,
        "text": "Nfzyxfrnok."
      }
    }
  },
  "family": "event_order",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 19.00720977783203,
      "gold_logprob": -2.715532064437866,
      "gold_margin": -2.6466827392578125,
      "gold_rank": 2,
      "target": 18480,
      "top1": 1186,
      "top_logit": 21.653892517089844,
      "top_ties": 1
    },
    "gold_probability": 0.06752124588089772,
    "gold_token": "Nu",
    "gold_token_id": 18480,
    "index": 0,
    "native": {
      "correct": false,
      "gold_logit": 19.0,
      "gold_logprob": -2.695312976837158,
      "gold_margin": -2.625,
      "gold_rank": 2,
      "target": 18480,
      "top1": 1186,
      "top_logit": 21.625,
      "top_ties": 1
    },
    "recorded_token": "N",
    "recorded_token_id": 1186,
    "teacher_fork_nll_fraction": 0.9913754722211333,
    "teacher_gold_probability": 0.06752155174966105
  },
  "id": "wb01-event_order-test-0015/s1/affected",
  "literal_matches_query_fields": [
    "left"
  ],
  "literal_matches_visible_fact_entity": true,
  "mean_teacher_nll": 0.33984455466270447,
  "memory": "Event Nenbohyoid occurs on day 27.\nEvent Nfzyxfrnok occurs on day 10.\nEvent Nuncjizqah occurs on day 17.\nEvent Nuakqvsbho occurs on day 8.",
  "mode": "affected",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nfzyxfrnok or Nuakqvsbho?",
  "query_spec": {
    "left": "Nfzyxfrnok",
    "op": "earlier",
    "right": "Nuakqvsbho"
  },
  "recorded_text": "Nfzyxfrnok.",
  "split": "test",
  "target": "Nuakqvsbho."
}
```

## wb01-event_order-test-0015/s1/unaffected

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": true,
        "text": "Nuncjizqah"
      },
      "latent": {
        "exact_match": false,
        "text": "Nenbohyoid"
      }
    },
    "v22": {
      "inline": {
        "exact_match": true,
        "text": "Nuncjizqah."
      },
      "latent": {
        "exact_match": false,
        "text": "Nenbohyoid."
      }
    }
  },
  "family": "event_order",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 17.47100830078125,
      "gold_logprob": -2.8014822006225586,
      "gold_margin": -2.710184097290039,
      "gold_rank": 2,
      "target": 11242,
      "top1": 1037,
      "top_logit": 20.18119239807129,
      "top_ties": 1
    },
    "gold_probability": 0.06568764898507176,
    "gold_token": "unc",
    "gold_token_id": 11242,
    "index": 1,
    "native": {
      "correct": false,
      "gold_logit": 17.5,
      "gold_logprob": -2.722844362258911,
      "gold_margin": -2.625,
      "gold_rank": 2,
      "target": 11242,
      "top1": 1037,
      "top_logit": 20.125,
      "top_ties": 1
    },
    "recorded_token": "en",
    "recorded_token_id": 1037,
    "teacher_fork_nll_fraction": 0.9964519899120379,
    "teacher_gold_probability": 0.07375564617793416
  },
  "id": "wb01-event_order-test-0015/s1/unaffected",
  "literal_matches_query_fields": [
    "right"
  ],
  "literal_matches_visible_fact_entity": true,
  "mean_teacher_nll": 0.3270350396633148,
  "memory": "Event Nenbohyoid occurs on day 27.\nEvent Nfzyxfrnok occurs on day 10.\nEvent Nuncjizqah occurs on day 17.\nEvent Nuakqvsbho occurs on day 8.",
  "mode": "unaffected",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nuncjizqah or Nenbohyoid?",
  "query_spec": {
    "left": "Nuncjizqah",
    "op": "earlier",
    "right": "Nenbohyoid"
  },
  "recorded_text": "Nenbohyoid.",
  "split": "test",
  "target": "Nuncjizqah."
}
```

## wb01-linked_location-ood-0023/s1/unaffected

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": true,
        "text": "Neruhfebov"
      },
      "latent": {
        "exact_match": false,
        "text": "Not specified."
      }
    },
    "v22": {
      "inline": {
        "exact_match": true,
        "text": "Neruhfebov."
      },
      "latent": {
        "exact_match": false,
        "text": "Nkxfboiobj."
      }
    }
  },
  "family": "linked_location",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 20.4963321685791,
      "gold_logprob": -0.8201817274093628,
      "gold_margin": -0.20345115661621094,
      "gold_rank": 2,
      "target": 1031,
      "top1": 29497,
      "top_logit": 20.699783325195312,
      "top_ties": 1
    },
    "gold_probability": 0.4295407294975505,
    "gold_token": "er",
    "gold_token_id": 1031,
    "index": 1,
    "native": {
      "correct": false,
      "gold_logit": 20.5,
      "gold_logprob": -0.8450387120246887,
      "gold_margin": -0.25,
      "gold_rank": 2,
      "target": 1031,
      "top1": 29497,
      "top_logit": 20.75,
      "top_ties": 1
    },
    "recorded_token": "k",
    "recorded_token_id": 29497,
    "teacher_fork_nll_fraction": 0.9608068675434323,
    "teacher_gold_probability": 0.48882320944068713
  },
  "id": "wb01-linked_location-ood-0023/s1/unaffected",
  "literal_matches_query_fields": [],
  "literal_matches_visible_fact_entity": true,
  "mean_teacher_nll": 0.09311892092227936,
  "memory": "Nmqthynrks is owned by Nxwqbhsiab.\nNbqpsfhojw is owned by Nmhhfjwxhf.\nNxwqbhsiab is at Nkxfboiobj.\nNmhhfjwxhf is at Neruhfebov.",
  "mode": "unaffected",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nbqpsfhojw?",
  "query_spec": {
    "op": "owner_location",
    "subject": "Nbqpsfhojw"
  },
  "recorded_text": "Nkxfboiobj.",
  "split": "ood",
  "target": "Neruhfebov."
}
```

## wb01-linked_location-ood-0056/s1/affected

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": false,
        "text": "Nlnvzyaype"
      },
      "latent": {
        "exact_match": false,
        "text": "Ngyuyonygy."
      }
    },
    "v22": {
      "inline": {
        "exact_match": false,
        "text": "Nlnvzyaype."
      },
      "latent": {
        "exact_match": false,
        "text": "Ngyuyony."
      }
    }
  },
  "family": "linked_location",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 19.81265640258789,
      "gold_logprob": -2.298532485961914,
      "gold_margin": -2.1923294067382812,
      "gold_rank": 2,
      "target": 5721,
      "top1": 1186,
      "top_logit": 22.004985809326172,
      "top_ties": 1
    },
    "gold_probability": 0.1066530538605465,
    "gold_token": "Nor",
    "gold_token_id": 5721,
    "index": 0,
    "native": {
      "correct": false,
      "gold_logit": 19.875,
      "gold_logprob": -2.2381742000579834,
      "gold_margin": -2.125,
      "gold_rank": 2,
      "target": 5721,
      "top1": 1186,
      "top_logit": 22.0,
      "top_ties": 1
    },
    "recorded_token": "N",
    "recorded_token_id": 1186,
    "teacher_fork_nll_fraction": 0.9839482323707416,
    "teacher_gold_probability": 0.10664768867282227
  },
  "id": "wb01-linked_location-ood-0056/s1/affected",
  "literal_matches_query_fields": [],
  "literal_matches_visible_fact_entity": false,
  "mean_teacher_nll": 0.3791230122248332,
  "memory": "Nfaghcptvy is at Norgyuyony.\nNrzdlstzsl is owned by Nfaghcptvy.\nNbnkdztqwd is owned by Ncjmdaonse.\nNcjmdaonse is at Nlnvzyaype.",
  "mode": "affected",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nrzdlstzsl?",
  "query_spec": {
    "op": "owner_location",
    "subject": "Nrzdlstzsl"
  },
  "recorded_text": "Ngyuyony.",
  "split": "ood",
  "target": "Norgyuyony."
}
```

## wb01-linked_location-ood-0058/s0/unaffected

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": true,
        "text": "Njkkqvkind"
      },
      "latent": {
        "exact_match": false,
        "text": "Ndojyaptgn"
      }
    },
    "v22": {
      "inline": {
        "exact_match": true,
        "text": "Njkkqvkind."
      },
      "latent": {
        "exact_match": false,
        "text": "Ndojyaptgn."
      }
    }
  },
  "family": "linked_location",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 19.868484497070312,
      "gold_logprob": -1.0971283912658691,
      "gold_margin": -0.6754131317138672,
      "gold_rank": 2,
      "target": 29536,
      "top1": 3200,
      "top_logit": 20.54389762878418,
      "top_ties": 1
    },
    "gold_probability": 0.3449909829883304,
    "gold_token": "j",
    "gold_token_id": 29536,
    "index": 1,
    "native": {
      "correct": false,
      "gold_logit": 19.875,
      "gold_logprob": -1.0642369985580444,
      "gold_margin": -0.625,
      "gold_rank": 2,
      "target": 29536,
      "top1": 3200,
      "top_logit": 20.5,
      "top_ties": 1
    },
    "recorded_token": "do",
    "recorded_token_id": 3200,
    "teacher_fork_nll_fraction": 0.9740693314953253,
    "teacher_gold_probability": 0.3736126349548721
  },
  "id": "wb01-linked_location-ood-0058/s0/unaffected",
  "literal_matches_query_fields": [],
  "literal_matches_visible_fact_entity": true,
  "mean_teacher_nll": 0.12634313106536865,
  "memory": "Nizooacxrl is owned by Nqtkfepcrk.\nNzgaohdxdq is owned by Nhwyspcdyf.\nNhwyspcdyf is at Njkkqvkind.\nNqtkfepcrk is at Ndojyaptgn.",
  "mode": "unaffected",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nzgaohdxdq?",
  "query_spec": {
    "op": "owner_location",
    "subject": "Nzgaohdxdq"
  },
  "recorded_text": "Ndojyaptgn.",
  "split": "ood",
  "target": "Njkkqvkind."
}
```

## wb01-linked_location-ood-0058/s1/affected

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": true,
        "text": "Nymszrcrff"
      },
      "latent": {
        "exact_match": true,
        "text": "Nymszrcrff"
      }
    },
    "v22": {
      "inline": {
        "exact_match": true,
        "text": "Nymszrcrff"
      },
      "latent": {
        "exact_match": false,
        "text": "Nymszrcrk."
      }
    }
  },
  "family": "linked_location",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 16.68450927734375,
      "gold_logprob": -1.7753098011016846,
      "gold_margin": -1.537160873413086,
      "gold_rank": 2,
      "target": 1264,
      "top1": 29497,
      "top_logit": 18.221670150756836,
      "top_ties": 1
    },
    "gold_probability": 0.15765295005963142,
    "gold_token": "ff",
    "gold_token_id": 1264,
    "index": 5,
    "native": {
      "correct": false,
      "gold_logit": 16.625,
      "gold_logprob": -1.8473591804504395,
      "gold_margin": -1.625,
      "gold_rank": 2,
      "target": 1264,
      "top1": 29497,
      "top_logit": 18.25,
      "top_ties": 1
    },
    "recorded_token": "k",
    "recorded_token_id": 29497,
    "teacher_fork_nll_fraction": 0.9480573081281837,
    "teacher_gold_probability": 0.19318967809259407
  },
  "id": "wb01-linked_location-ood-0058/s1/affected",
  "literal_matches_query_fields": [],
  "literal_matches_visible_fact_entity": false,
  "mean_teacher_nll": 0.2167699635028839,
  "memory": "Nizooacxrl is owned by Nqtkfepcrk.\nNzgaohdxdq is owned by Nhwyspcdyf.\nNhwyspcdyf is at Njkkqvkind.\nNqtkfepcrk is at Nymszrcrff.",
  "mode": "affected",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nizooacxrl?",
  "query_spec": {
    "op": "owner_location",
    "subject": "Nizooacxrl"
  },
  "recorded_text": "Nymszrcrk.",
  "split": "ood",
  "target": "Nymszrcrff."
}
```

## wb01-linked_location-ood-0058/s1/unaffected

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": false,
        "text": "Nymszrcrff"
      },
      "latent": {
        "exact_match": false,
        "text": "Nymszrcrff"
      }
    },
    "v22": {
      "inline": {
        "exact_match": true,
        "text": "Njkkqvkind."
      },
      "latent": {
        "exact_match": false,
        "text": "Nymszrcrff."
      }
    }
  },
  "family": "linked_location",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 18.518861770629883,
      "gold_logprob": -2.990365505218506,
      "gold_margin": -2.9383678436279297,
      "gold_rank": 2,
      "target": 1186,
      "top1": 21036,
      "top_logit": 21.457229614257812,
      "top_ties": 1
    },
    "gold_probability": 0.04740759433495999,
    "gold_token": "N",
    "gold_token_id": 1186,
    "index": 0,
    "native": {
      "correct": false,
      "gold_logit": 18.5,
      "gold_logprob": -3.0489728450775146,
      "gold_margin": -3.0,
      "gold_rank": 2,
      "target": 1186,
      "top1": 21036,
      "top_logit": 21.5,
      "top_ties": 1
    },
    "recorded_token": "Ny",
    "recorded_token_id": 21036,
    "teacher_fork_nll_fraction": 0.9912690684161973,
    "teacher_gold_probability": 0.053379965246107254
  },
  "id": "wb01-linked_location-ood-0058/s1/unaffected",
  "literal_matches_query_fields": [],
  "literal_matches_visible_fact_entity": true,
  "mean_teacher_nll": 0.36951619386672974,
  "memory": "Nizooacxrl is owned by Nqtkfepcrk.\nNzgaohdxdq is owned by Nhwyspcdyf.\nNhwyspcdyf is at Njkkqvkind.\nNqtkfepcrk is at Nymszrcrff.",
  "mode": "unaffected",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nzgaohdxdq?",
  "query_spec": {
    "op": "owner_location",
    "subject": "Nzgaohdxdq"
  },
  "recorded_text": "Nymszrcrff.",
  "split": "ood",
  "target": "Njkkqvkind."
}
```

## wb01-order-test-0007/s0/unaffected

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": false,
        "text": "Nahcvzocje"
      },
      "latent": {
        "exact_match": false,
        "text": "Nahcvzocje"
      }
    },
    "v22": {
      "inline": {
        "exact_match": false,
        "text": "Nahcvzocje."
      },
      "latent": {
        "exact_match": false,
        "text": "Nahcvzocje."
      }
    }
  },
  "family": "order",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 17.508766174316406,
      "gold_logprob": -3.0043225288391113,
      "gold_margin": -2.9523849487304688,
      "gold_rank": 2,
      "target": 1186,
      "top1": 29371,
      "top_logit": 20.461151123046875,
      "top_ties": 1
    },
    "gold_probability": 0.047378170844840986,
    "gold_token": "N",
    "gold_token_id": 1186,
    "index": 0,
    "native": {
      "correct": false,
      "gold_logit": 17.5,
      "gold_logprob": -3.049593687057495,
      "gold_margin": -3.0,
      "gold_rank": 2,
      "target": 1186,
      "top1": 29371,
      "top_logit": 20.5,
      "top_ties": 1
    },
    "recorded_token": "Nah",
    "recorded_token_id": 29371,
    "teacher_fork_nll_fraction": 0.9814770833144428,
    "teacher_gold_probability": 0.0600280849785184
  },
  "id": "wb01-order-test-0007/s0/unaffected",
  "literal_matches_query_fields": [
    "right"
  ],
  "literal_matches_visible_fact_entity": true,
  "mean_teacher_nll": 0.3184477753109402,
  "memory": "Nbzfnerjmv is ranked above Nahcvzocje.\nNnzfosszql is ranked above Nonfrecqxb.\nNwpkirypuq is ranked above Nbzfnerjmv.\nNonfrecqxb is ranked above Nwpkirypuq.",
  "mode": "unaffected",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Nbzfnerjmv or Nahcvzocje?",
  "query_spec": {
    "left": "Nbzfnerjmv",
    "op": "higher",
    "right": "Nahcvzocje"
  },
  "recorded_text": "Nahcvzocje.",
  "split": "test",
  "target": "Nbzfnerjmv."
}
```

## wb01-order-test-0007/s1/unaffected

```json
{
  "comparisons": {
    "base": {
      "inline": {
        "exact_match": false,
        "text": "Nahcvzocje"
      },
      "latent": {
        "exact_match": false,
        "text": "Nahcvzocje"
      }
    },
    "v22": {
      "inline": {
        "exact_match": false,
        "text": "Nahcvzocje."
      },
      "latent": {
        "exact_match": false,
        "text": "Nahcvzocje."
      }
    }
  },
  "family": "order",
  "first_fork": {
    "fp32_head": {
      "correct": false,
      "gold_logit": 17.722259521484375,
      "gold_logprob": -2.6056928634643555,
      "gold_margin": -2.5279617309570312,
      "gold_rank": 2,
      "target": 1186,
      "top1": 29371,
      "top_logit": 20.250221252441406,
      "top_ties": 1
    },
    "gold_probability": 0.07578786764062813,
    "gold_token": "N",
    "gold_token_id": 1186,
    "index": 0,
    "native": {
      "correct": false,
      "gold_logit": 17.75,
      "gold_logprob": -2.579817056655884,
      "gold_margin": -2.5,
      "gold_rank": 2,
      "target": 1186,
      "top1": 29371,
      "top_logit": 20.25,
      "top_ties": 1
    },
    "recorded_token": "Nah",
    "recorded_token_id": 29371,
    "teacher_fork_nll_fraction": 0.9793573497012859,
    "teacher_gold_probability": 0.08502808588117299
  },
  "id": "wb01-order-test-0007/s1/unaffected",
  "literal_matches_query_fields": [
    "right"
  ],
  "literal_matches_visible_fact_entity": true,
  "mean_teacher_nll": 0.27963617112901473,
  "memory": "Nbzfnerjmv is ranked above Nahcvzocje.\nNwpkirypuq is ranked above Nonfrecqxb.\nNnzfosszql is ranked above Nbzfnerjmv.\nNonfrecqxb is ranked above Nnzfosszql.",
  "mode": "unaffected",
  "query": "Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Nbzfnerjmv or Nahcvzocje?",
  "query_spec": {
    "left": "Nbzfnerjmv",
    "op": "higher",
    "right": "Nahcvzocje"
  },
  "recorded_text": "Nahcvzocje.",
  "split": "test",
  "target": "Nbzfnerjmv."
}
```
