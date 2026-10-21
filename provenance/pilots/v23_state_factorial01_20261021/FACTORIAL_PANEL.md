# W/Q/R fixed-prefix panel: all 96 world rows

This assay generates no answers. Tables show the first disagreement with
the **oracle-provided prefix**, not a hybrid free-generation continuation.
Only the two explicitly labeled historical strings are actual generated answers.
W = memory writer; Q = question AND continuation encoder; R = upper reader/head.
Token strings use JSON quoting to preserve spaces and special symbols.

## wb01-event_order-test-0006/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nbwxsmihfd or Nopqjltbgi?
```

Historical base generation (eos):

```text
Not specified (since the given memory facts do not provide a relationship between the two events to determine their order).
```

Historical v22 generation (eos):

```text
Nbwxsmihfd.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 2/4 | 2 | `"."` | `"("` | -1.875 |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -1.125 |
| none | v22 | v22 | 3/4 | 0 | `"Not"` | `"N"` | 0 |

## wb01-event_order-test-0006/s0/affected

Mode: affected; target: `Nbwxsmihfd.`.

Memory:

```text
Event Nbwxsmihfd occurs on day 6.
Event Nopqjltbgi occurs on day 17.
Event Nmmkxozbif occurs on day 21.
Event Nayerhmvgg occurs on day 28.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nbwxsmihfd or Nopqjltbgi?
```

Historical base generation (eos):

```text
Nbwxsmihfd occurs earlier. (Day 6 < Day 17)
```

Historical v22 generation (eos):

```text
Nbwxsmihfd.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 6 | `"."` | `"occurs"` | -5.125 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 6/8 | 6 | `"."` | `"</s>"` | -5.4375 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 6/8 | 6 | `"."` | `"occurs"` | -5 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 6/8 | 6 | `"."` | `"</s>"` | -5.625 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-event_order-test-0006/s0/unaffected

Mode: unaffected; target: `Nmmkxozbif.`.

Memory:

```text
Event Nbwxsmihfd occurs on day 6.
Event Nopqjltbgi occurs on day 17.
Event Nmmkxozbif occurs on day 21.
Event Nayerhmvgg occurs on day 28.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nmmkxozbif or Nayerhmvgg?
```

Historical base generation (eos):

```text
Nmmkxozbif
```

Historical v22 generation (eos):

```text
Nmmkxozbif.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/9 | 7 | `"."` | `"</s>"` | -6.3125 |
| base | base | v22 | 9/9 | — | — | — | — |
| base | v22 | base | 7/9 | 7 | `"."` | `"</s>"` | -7.875 |
| base | v22 | v22 | 9/9 | — | — | — | — |
| v22 | base | base | 7/9 | 7 | `"."` | `"</s>"` | -6.625 |
| v22 | base | v22 | 9/9 | — | — | — | — |
| v22 | v22 | base | 7/9 | 7 | `"."` | `"</s>"` | -8.1875 |
| v22 | v22 | v22 | 9/9 | — | — | — | — |

## wb01-event_order-test-0006/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Nocpawjmki is at Nqinsahklu.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nbwxsmihfd or Nopqjltbgi?
```

Historical base generation (eos):

```text
Not specified (insufficient information)
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 2/4 | 2 | `"."` | `"("` | -0.875 |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -0.25 |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 2/4 | 2 | `"."` | `"("` | -0.875 |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -0.25 |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-event_order-test-0006/s1/affected

Mode: affected; target: `Nopqjltbgi.`.

Memory:

```text
Event Nbwxsmihfd occurs on day 17.
Event Nopqjltbgi occurs on day 6.
Event Nmmkxozbif occurs on day 21.
Event Nayerhmvgg occurs on day 28.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nbwxsmihfd or Nopqjltbgi?
```

Historical base generation (eos):

```text
Nbwxsmihfd occurs earlier. (Day 17 < Day 6)
```

Historical v22 generation (eos):

```text
Nbwxsmihfd.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/9 | 1 | `"op"` | `"b"` | -5.875 |
| base | base | v22 | 8/9 | 1 | `"op"` | `"b"` | -2.375 |
| base | v22 | base | 6/9 | 1 | `"op"` | `"b"` | -5.75 |
| base | v22 | v22 | 8/9 | 1 | `"op"` | `"b"` | -2.25 |
| v22 | base | base | 6/9 | 1 | `"op"` | `"b"` | -5.75 |
| v22 | base | v22 | 8/9 | 1 | `"op"` | `"b"` | -2 |
| v22 | v22 | base | 6/9 | 1 | `"op"` | `"b"` | -5.625 |
| v22 | v22 | v22 | 8/9 | 1 | `"op"` | `"b"` | -2 |

## wb01-event_order-test-0006/s1/unaffected

Mode: unaffected; target: `Nmmkxozbif.`.

Memory:

```text
Event Nbwxsmihfd occurs on day 17.
Event Nopqjltbgi occurs on day 6.
Event Nmmkxozbif occurs on day 21.
Event Nayerhmvgg occurs on day 28.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nmmkxozbif or Nayerhmvgg?
```

Historical base generation (eos):

```text
Nmmkxozbif
```

Historical v22 generation (eos):

```text
Nmmkxozbif.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/9 | 7 | `"."` | `"</s>"` | -5.9375 |
| base | base | v22 | 9/9 | — | — | — | — |
| base | v22 | base | 7/9 | 7 | `"."` | `"</s>"` | -7.125 |
| base | v22 | v22 | 9/9 | — | — | — | — |
| v22 | base | base | 7/9 | 7 | `"."` | `"</s>"` | -6.125 |
| v22 | base | v22 | 9/9 | — | — | — | — |
| v22 | v22 | base | 7/9 | 7 | `"."` | `"</s>"` | -7.625 |
| v22 | v22 | v22 | 9/9 | — | — | — | — |

## wb01-event_order-test-0015/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nfzyxfrnok or Nuakqvsbho?
```

Historical base generation (eos):

```text
Not specified
```

Historical v22 generation (eos):

```text
Nfzyxfrnok.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 3/4 | 2 | `"."` | `"</s>"` | -0.75 |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -1 |
| none | v22 | v22 | 3/4 | 0 | `"Not"` | `"N"` | -0.25 |

## wb01-event_order-test-0015/s0/affected

Mode: affected; target: `Nfzyxfrnok.`.

Memory:

```text
Event Nenbohyoid occurs on day 27.
Event Nfzyxfrnok occurs on day 8.
Event Nuncjizqah occurs on day 17.
Event Nuakqvsbho occurs on day 10.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nfzyxfrnok or Nuakqvsbho?
```

Historical base generation (eos):

```text
Nfzyxfrnok
```

Historical v22 generation (eos):

```text
Nfzyxfrnok.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/9 | 7 | `"."` | `"</s>"` | -2.6875 |
| base | base | v22 | 9/9 | — | — | — | — |
| base | v22 | base | 7/9 | 7 | `"."` | `"</s>"` | -3.75 |
| base | v22 | v22 | 9/9 | — | — | — | — |
| v22 | base | base | 7/9 | 7 | `"."` | `"</s>"` | -2.875 |
| v22 | base | v22 | 9/9 | — | — | — | — |
| v22 | v22 | base | 7/9 | 7 | `"."` | `"</s>"` | -4.125 |
| v22 | v22 | v22 | 9/9 | — | — | — | — |

## wb01-event_order-test-0015/s0/unaffected

Mode: unaffected; target: `Nuncjizqah.`.

Memory:

```text
Event Nenbohyoid occurs on day 27.
Event Nfzyxfrnok occurs on day 8.
Event Nuncjizqah occurs on day 17.
Event Nuakqvsbho occurs on day 10.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nuncjizqah or Nenbohyoid?
```

Historical base generation (eos):

```text
Nenbohyoid
```

Historical v22 generation (eos):

```text
Nenbohyoid.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 5/8 | 1 | `"unc"` | `"en"` | -3.375 |
| base | base | v22 | 7/8 | 1 | `"unc"` | `"en"` | -2.875 |
| base | v22 | base | 5/8 | 1 | `"unc"` | `"en"` | -3.125 |
| base | v22 | v22 | 7/8 | 1 | `"unc"` | `"en"` | -2.625 |
| v22 | base | base | 5/8 | 1 | `"unc"` | `"en"` | -3.375 |
| v22 | base | v22 | 7/8 | 1 | `"unc"` | `"en"` | -2.875 |
| v22 | v22 | base | 5/8 | 1 | `"unc"` | `"en"` | -3.25 |
| v22 | v22 | v22 | 7/8 | 1 | `"unc"` | `"en"` | -2.625 |

## wb01-event_order-test-0015/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Naajtqkjfv is at Ndgkfnevba.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nfzyxfrnok or Nuakqvsbho?
```

Historical base generation (eos):

```text
Not specified (insufficient information)
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 3/4 | 2 | `"."` | `"("` | -1 |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -0.875 |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 3/4 | 2 | `"."` | `"("` | -0.875 |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -0.875 |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-event_order-test-0015/s1/affected

Mode: affected; target: `Nuakqvsbho.`.

Memory:

```text
Event Nenbohyoid occurs on day 27.
Event Nfzyxfrnok occurs on day 10.
Event Nuncjizqah occurs on day 17.
Event Nuakqvsbho occurs on day 8.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nfzyxfrnok or Nuakqvsbho?
```

Historical base generation (eos):

```text
Nfzyxfrnok occurs earlier. (Day 10 < Day 8)
```

Historical v22 generation (eos):

```text
Nfzyxfrnok.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 5/8 | 0 | `"Nu"` | `"N"` | -3.875 |
| base | base | v22 | 7/8 | 0 | `"Nu"` | `"N"` | -2.625 |
| base | v22 | base | 5/8 | 0 | `"Nu"` | `"N"` | -3.625 |
| base | v22 | v22 | 7/8 | 0 | `"Nu"` | `"N"` | -2.75 |
| v22 | base | base | 5/8 | 0 | `"Nu"` | `"N"` | -4 |
| v22 | base | v22 | 7/8 | 0 | `"Nu"` | `"N"` | -2.625 |
| v22 | v22 | base | 5/8 | 0 | `"Nu"` | `"N"` | -3.5 |
| v22 | v22 | v22 | 7/8 | 0 | `"Nu"` | `"N"` | -2.625 |

## wb01-event_order-test-0015/s1/unaffected

Mode: unaffected; target: `Nuncjizqah.`.

Memory:

```text
Event Nenbohyoid occurs on day 27.
Event Nfzyxfrnok occurs on day 10.
Event Nuncjizqah occurs on day 17.
Event Nuakqvsbho occurs on day 8.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which event occurs earlier, Nuncjizqah or Nenbohyoid?
```

Historical base generation (eos):

```text
Nenbohyoid
```

Historical v22 generation (eos):

```text
Nenbohyoid.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 5/8 | 1 | `"unc"` | `"en"` | -3 |
| base | base | v22 | 7/8 | 1 | `"unc"` | `"en"` | -2.75 |
| base | v22 | base | 5/8 | 1 | `"unc"` | `"en"` | -2.625 |
| base | v22 | v22 | 7/8 | 1 | `"unc"` | `"en"` | -2.625 |
| v22 | base | base | 5/8 | 1 | `"unc"` | `"en"` | -3.125 |
| v22 | base | v22 | 7/8 | 1 | `"unc"` | `"en"` | -2.75 |
| v22 | v22 | base | 5/8 | 1 | `"unc"` | `"en"` | -2.875 |
| v22 | v22 | v22 | 7/8 | 1 | `"unc"` | `"en"` | -2.625 |

## wb01-inventory-test-0008/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. How many tokens does Nmmzqyvtti have after receiving the tokens?
```

Historical base generation (length):

```text
Not specified. The memory facts do not provide information about the number of tokens received by Nmmzqyvtti
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 3/4 | 3 | `"</s>"` | `"The"` | -2 |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -0.125 |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-inventory-test-0008/s0/affected

Mode: affected; target: `21.`.

Memory:

```text
Nvjglxxawo receives 2 more tokens; no tokens are removed.
Nmmzqyvtti initially has 11 tokens.
Nmmzqyvtti receives 10 more tokens; no tokens are removed.
Nvjglxxawo initially has 17 tokens.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. How many tokens does Nmmzqyvtti have after receiving the tokens?
```

Historical base generation (eos):

```text
21
```

Historical v22 generation (eos):

```text
21.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 4/5 | 3 | `"."` | `"</s>"` | -11.6875 |
| base | base | v22 | 5/5 | — | — | — | — |
| base | v22 | base | 4/5 | 3 | `"."` | `"</s>"` | -11.6875 |
| base | v22 | v22 | 5/5 | — | — | — | — |
| v22 | base | base | 4/5 | 3 | `"."` | `"</s>"` | -11.625 |
| v22 | base | v22 | 5/5 | — | — | — | — |
| v22 | v22 | base | 4/5 | 3 | `"."` | `"</s>"` | -11.9375 |
| v22 | v22 | v22 | 5/5 | — | — | — | — |

## wb01-inventory-test-0008/s0/unaffected

Mode: unaffected; target: `19.`.

Memory:

```text
Nvjglxxawo receives 2 more tokens; no tokens are removed.
Nmmzqyvtti initially has 11 tokens.
Nmmzqyvtti receives 10 more tokens; no tokens are removed.
Nvjglxxawo initially has 17 tokens.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. How many tokens does Nvjglxxawo have after receiving the tokens?
```

Historical base generation (eos):

```text
27
```

Historical v22 generation (eos):

```text
19.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 3/5 | 1 | `"1"` | `"2"` | -1.375 |
| base | base | v22 | 5/5 | — | — | — | — |
| base | v22 | base | 3/5 | 1 | `"1"` | `"2"` | -1.125 |
| base | v22 | v22 | 5/5 | — | — | — | — |
| v22 | base | base | 3/5 | 1 | `"1"` | `"2"` | -1.625 |
| v22 | base | v22 | 5/5 | — | — | — | — |
| v22 | v22 | base | 3/5 | 1 | `"1"` | `"2"` | -1 |
| v22 | v22 | v22 | 5/5 | — | — | — | — |

## wb01-inventory-test-0008/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Nmzevwqptt is at Nbuhsrerro.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. How many tokens does Nmmzqyvtti have after receiving the tokens?
```

Historical base generation (length):

```text
Not specified. The given memory facts do not provide information about the number of tokens received by Nmmzqyv
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 3/4 | 3 | `"</s>"` | `"The"` | -4.375 |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 3/4 | 3 | `"</s>"` | `"The"` | -2 |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 3/4 | 3 | `"</s>"` | `"The"` | -4.1875 |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 3/4 | 3 | `"</s>"` | `"The"` | -1.875 |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-inventory-test-0008/s1/affected

Mode: affected; target: `24.`.

Memory:

```text
Nvjglxxawo receives 2 more tokens; no tokens are removed.
Nmmzqyvtti initially has 14 tokens.
Nmmzqyvtti receives 10 more tokens; no tokens are removed.
Nvjglxxawo initially has 17 tokens.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. How many tokens does Nmmzqyvtti have after receiving the tokens?
```

Historical base generation (eos):

```text
24
```

Historical v22 generation (eos):

```text
24.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 4/5 | 3 | `"."` | `"</s>"` | -11.4375 |
| base | base | v22 | 5/5 | — | — | — | — |
| base | v22 | base | 4/5 | 3 | `"."` | `"</s>"` | -11.5 |
| base | v22 | v22 | 5/5 | — | — | — | — |
| v22 | base | base | 4/5 | 3 | `"."` | `"</s>"` | -11.375 |
| v22 | base | v22 | 5/5 | — | — | — | — |
| v22 | v22 | base | 4/5 | 3 | `"."` | `"</s>"` | -11.625 |
| v22 | v22 | v22 | 5/5 | — | — | — | — |

## wb01-inventory-test-0008/s1/unaffected

Mode: unaffected; target: `19.`.

Memory:

```text
Nvjglxxawo receives 2 more tokens; no tokens are removed.
Nmmzqyvtti initially has 14 tokens.
Nmmzqyvtti receives 10 more tokens; no tokens are removed.
Nvjglxxawo initially has 17 tokens.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. How many tokens does Nvjglxxawo have after receiving the tokens?
```

Historical base generation (eos):

```text
24
```

Historical v22 generation (eos):

```text
19.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 3/5 | 1 | `"1"` | `"2"` | -2.125 |
| base | base | v22 | 5/5 | — | — | — | — |
| base | v22 | base | 3/5 | 1 | `"1"` | `"2"` | -1.875 |
| base | v22 | v22 | 5/5 | — | — | — | — |
| v22 | base | base | 3/5 | 1 | `"1"` | `"2"` | -2.375 |
| v22 | base | v22 | 5/5 | — | — | — | — |
| v22 | v22 | base | 3/5 | 1 | `"1"` | `"2"` | -2 |
| v22 | v22 | v22 | 5/5 | — | — | — | — |

## wb01-inventory-test-0009/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. How many tokens does Nhcltkbtmx have after receiving the tokens?
```

Historical base generation (length):

```text
Not specified (The given memory facts do not provide information about the initial number of tokens or the tokens received by Nh
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 2/4 | 2 | `"."` | `"("` | -1.625 |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"("` | -0.125 |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-inventory-test-0009/s0/affected

Mode: affected; target: `20.`.

Memory:

```text
Nhcltkbtmx receives 1 more tokens; no tokens are removed.
Nipqhqghht initially has 17 tokens.
Nipqhqghht receives 2 more tokens; no tokens are removed.
Nhcltkbtmx initially has 19 tokens.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. How many tokens does Nhcltkbtmx have after receiving the tokens?
```

Historical base generation (eos):

```text
21
```

Historical v22 generation (eos):

```text
20.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 3/5 | 2 | `"0"` | `"1"` | -1.625 |
| base | base | v22 | 5/5 | — | — | — | — |
| base | v22 | base | 3/5 | 2 | `"0"` | `"1"` | -1.75 |
| base | v22 | v22 | 5/5 | — | — | — | — |
| v22 | base | base | 3/5 | 2 | `"0"` | `"1"` | -1.625 |
| v22 | base | v22 | 5/5 | — | — | — | — |
| v22 | v22 | base | 3/5 | 2 | `"0"` | `"1"` | -1.5 |
| v22 | v22 | v22 | 5/5 | — | — | — | — |

## wb01-inventory-test-0009/s0/unaffected

Mode: unaffected; target: `19.`.

Memory:

```text
Nhcltkbtmx receives 1 more tokens; no tokens are removed.
Nipqhqghht initially has 17 tokens.
Nipqhqghht receives 2 more tokens; no tokens are removed.
Nhcltkbtmx initially has 19 tokens.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. How many tokens does Nipqhqghht have after receiving the tokens?
```

Historical base generation (eos):

```text
19
```

Historical v22 generation (eos):

```text
19.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 4/5 | 3 | `"."` | `"</s>"` | -11.03125 |
| base | base | v22 | 5/5 | — | — | — | — |
| base | v22 | base | 4/5 | 3 | `"."` | `"</s>"` | -11.625 |
| base | v22 | v22 | 5/5 | — | — | — | — |
| v22 | base | base | 4/5 | 3 | `"."` | `"</s>"` | -11.125 |
| v22 | base | v22 | 5/5 | — | — | — | — |
| v22 | v22 | base | 4/5 | 3 | `"."` | `"</s>"` | -11.5625 |
| v22 | v22 | v22 | 5/5 | — | — | — | — |

## wb01-inventory-test-0009/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Nzvcrdwvhr is at Nzcawvfnfq.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. How many tokens does Nhcltkbtmx have after receiving the tokens?
```

Historical base generation (length):

```text
Not specified. The given memory facts do not provide information about the number of tokens received by Nhcltkbtmx
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 3/4 | 3 | `"</s>"` | `"The"` | -4 |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 3/4 | 3 | `"</s>"` | `"The"` | -2 |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 3/4 | 3 | `"</s>"` | `"The"` | -3.875 |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 3/4 | 3 | `"</s>"` | `"The"` | -1.75 |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-inventory-test-0009/s1/affected

Mode: affected; target: `23.`.

Memory:

```text
Nhcltkbtmx receives 1 more tokens; no tokens are removed.
Nipqhqghht initially has 17 tokens.
Nipqhqghht receives 2 more tokens; no tokens are removed.
Nhcltkbtmx initially has 22 tokens.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. How many tokens does Nhcltkbtmx have after receiving the tokens?
```

Historical base generation (eos):

```text
24
```

Historical v22 generation (eos):

```text
23.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 2/5 | 2 | `"3"` | `"4"` | -3.875 |
| base | base | v22 | 5/5 | — | — | — | — |
| base | v22 | base | 3/5 | 2 | `"3"` | `"4"` | -3.875 |
| base | v22 | v22 | 5/5 | — | — | — | — |
| v22 | base | base | 2/5 | 2 | `"3"` | `"4"` | -3.5 |
| v22 | base | v22 | 5/5 | — | — | — | — |
| v22 | v22 | base | 3/5 | 2 | `"3"` | `"4"` | -3.75 |
| v22 | v22 | v22 | 5/5 | — | — | — | — |

## wb01-inventory-test-0009/s1/unaffected

Mode: unaffected; target: `19.`.

Memory:

```text
Nhcltkbtmx receives 1 more tokens; no tokens are removed.
Nipqhqghht initially has 17 tokens.
Nipqhqghht receives 2 more tokens; no tokens are removed.
Nhcltkbtmx initially has 22 tokens.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. How many tokens does Nipqhqghht have after receiving the tokens?
```

Historical base generation (eos):

```text
19
```

Historical v22 generation (eos):

```text
19.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 4/5 | 3 | `"."` | `"</s>"` | -12 |
| base | base | v22 | 5/5 | — | — | — | — |
| base | v22 | base | 4/5 | 3 | `"."` | `"</s>"` | -12.375 |
| base | v22 | v22 | 5/5 | — | — | — | — |
| v22 | base | base | 4/5 | 3 | `"."` | `"</s>"` | -12.0625 |
| v22 | base | v22 | 5/5 | — | — | — | — |
| v22 | v22 | base | 4/5 | 3 | `"."` | `"</s>"` | -12.375 |
| v22 | v22 | v22 | 5/5 | — | — | — | — |

## wb01-linked_location-ood-0011/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nbzlbkfshv?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 4/4 | — | — | — | — |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 4/4 | — | — | — | — |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-linked_location-ood-0011/s0/affected

Mode: affected; target: `Nylmrncung.`.

Memory:

```text
Ngthunmosg is owned by Noyeycutqo.
Nbzlbkfshv is owned by Nasxzniefj.
Noyeycutqo is at Neobmdufca.
Nasxzniefj is at Nylmrncung.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nbzlbkfshv?
```

Historical base generation (eos):

```text
Nylmrncung
```

Historical v22 generation (eos):

```text
Nylmrncung.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/7 | 5 | `"."` | `"</s>"` | -4.875 |
| base | base | v22 | 7/7 | — | — | — | — |
| base | v22 | base | 6/7 | 5 | `"."` | `"</s>"` | -4.125 |
| base | v22 | v22 | 7/7 | — | — | — | — |
| v22 | base | base | 6/7 | 5 | `"."` | `"</s>"` | -5 |
| v22 | base | v22 | 7/7 | — | — | — | — |
| v22 | v22 | base | 6/7 | 5 | `"."` | `"</s>"` | -4.125 |
| v22 | v22 | v22 | 7/7 | — | — | — | — |

## wb01-linked_location-ood-0011/s0/unaffected

Mode: unaffected; target: `Neobmdufca.`.

Memory:

```text
Ngthunmosg is owned by Noyeycutqo.
Nbzlbkfshv is owned by Nasxzniefj.
Noyeycutqo is at Neobmdufca.
Nasxzniefj is at Nylmrncung.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Ngthunmosg?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Neobmdufca.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 0 | `"Ne"` | `"Not"` | -2.5 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 6/8 | 0 | `"Ne"` | `"Not"` | -1.5 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 6/8 | 0 | `"Ne"` | `"Not"` | -2.25 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 6/8 | 0 | `"Ne"` | `"Not"` | -0.875 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-linked_location-ood-0011/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Npwsfauoli is at Nvqhppbril.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nbzlbkfshv?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 4/4 | — | — | — | — |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 4/4 | — | — | — | — |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 4/4 | — | — | — | — |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 4/4 | — | — | — | — |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-linked_location-ood-0011/s1/affected

Mode: affected; target: `Nzemxemwnl.`.

Memory:

```text
Ngthunmosg is owned by Noyeycutqo.
Nbzlbkfshv is owned by Nasxzniefj.
Noyeycutqo is at Neobmdufca.
Nasxzniefj is at Nzemxemwnl.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nbzlbkfshv?
```

Historical base generation (eos):

```text
Nzemxemwnl
```

Historical v22 generation (eos):

```text
Nzemxemwnl.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -7 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -5.75 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -6.625 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -5.75 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-linked_location-ood-0011/s1/unaffected

Mode: unaffected; target: `Neobmdufca.`.

Memory:

```text
Ngthunmosg is owned by Noyeycutqo.
Nbzlbkfshv is owned by Nasxzniefj.
Noyeycutqo is at Neobmdufca.
Nasxzniefj is at Nzemxemwnl.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Ngthunmosg?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Neobmdufca.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 0 | `"Ne"` | `"Not"` | -2.125 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 6/8 | 0 | `"Ne"` | `"Not"` | -0.75 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 6/8 | 0 | `"Ne"` | `"Not"` | -1.375 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 6/8 | 0 | `"Ne"` | `"Not"` | -0.5 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-linked_location-ood-0023/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nmqthynrks?
```

Historical base generation (eos):

```text
Not specified
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 3/4 | 2 | `"."` | `"</s>"` | -0.875 |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -1.375 |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-linked_location-ood-0023/s0/affected

Mode: affected; target: `Nxepypwlad.`.

Memory:

```text
Nmqthynrks is owned by Nxwqbhsiab.
Nbqpsfhojw is owned by Nmhhfjwxhf.
Nxwqbhsiab is at Nxepypwlad.
Nmhhfjwxhf is at Neruhfebov.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nmqthynrks?
```

Historical base generation (eos):

```text
At Nxepypwlad.
```

Historical v22 generation (eos):

```text
Nxepypwlad.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 0 | `"N"` | `"At"` | -0.625 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 6/8 | 0 | `"N"` | `"At"` | -0.25 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 6/8 | 0 | `"N"` | `"At"` | -0.75 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 6/8 | 0 | `"N"` | `"At"` | -0.375 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-linked_location-ood-0023/s0/unaffected

Mode: unaffected; target: `Neruhfebov.`.

Memory:

```text
Nmqthynrks is owned by Nxwqbhsiab.
Nbqpsfhojw is owned by Nmhhfjwxhf.
Nxwqbhsiab is at Nxepypwlad.
Nmhhfjwxhf is at Neruhfebov.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nbqpsfhojw?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Neruhfebov.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 0 | `"N"` | `"Not"` | -2.625 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 6/8 | 0 | `"N"` | `"Not"` | -1.875 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 6/8 | 0 | `"N"` | `"Not"` | -2.5 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 6/8 | 0 | `"N"` | `"Not"` | -2 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-linked_location-ood-0023/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Npbgbpvegf is at Nvgzbkspmk.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nmqthynrks?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 4/4 | — | — | — | — |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 4/4 | — | — | — | — |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 4/4 | — | — | — | — |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 4/4 | — | — | — | — |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-linked_location-ood-0023/s1/affected

Mode: affected; target: `Nkxfboiobj.`.

Memory:

```text
Nmqthynrks is owned by Nxwqbhsiab.
Nbqpsfhojw is owned by Nmhhfjwxhf.
Nxwqbhsiab is at Nkxfboiobj.
Nmhhfjwxhf is at Neruhfebov.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nmqthynrks?
```

Historical base generation (eos):

```text
Nkxfboiobj
```

Historical v22 generation (eos):

```text
Nkxfboiobj.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -6.125 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -5.75 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -6.125 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -5.5 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-linked_location-ood-0023/s1/unaffected

Mode: unaffected; target: `Neruhfebov.`.

Memory:

```text
Nmqthynrks is owned by Nxwqbhsiab.
Nbqpsfhojw is owned by Nmhhfjwxhf.
Nxwqbhsiab is at Nkxfboiobj.
Nmhhfjwxhf is at Neruhfebov.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nbqpsfhojw?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Nkxfboiobj.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 0 | `"N"` | `"Not"` | -1.875 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 6/8 | 0 | `"N"` | `"Not"` | -1.375 |
| base | v22 | v22 | 7/8 | 1 | `"er"` | `"k"` | -0.5 |
| v22 | base | base | 6/8 | 0 | `"N"` | `"Not"` | -1.875 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 6/8 | 0 | `"N"` | `"Not"` | -1.125 |
| v22 | v22 | v22 | 7/8 | 1 | `"er"` | `"k"` | -0.25 |

## wb01-linked_location-ood-0056/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nrzdlstzsl?
```

Historical base generation (eos):

```text
Not specified
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 3/4 | 2 | `"."` | `"</s>"` | -0.125 |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -0.375 |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-linked_location-ood-0056/s0/affected

Mode: affected; target: `Nlvynziims.`.

Memory:

```text
Nfaghcptvy is at Nlvynziims.
Nrzdlstzsl is owned by Nfaghcptvy.
Nbnkdztqwd is owned by Ncjmdaonse.
Ncjmdaonse is at Nlnvzyaype.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nrzdlstzsl?
```

Historical base generation (eos):

```text
Nlvynziims
```

Historical v22 generation (eos):

```text
Nlvynziims.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/7 | 5 | `"."` | `"</s>"` | -5.375 |
| base | base | v22 | 7/7 | — | — | — | — |
| base | v22 | base | 6/7 | 5 | `"."` | `"</s>"` | -4.875 |
| base | v22 | v22 | 7/7 | — | — | — | — |
| v22 | base | base | 6/7 | 5 | `"."` | `"</s>"` | -5 |
| v22 | base | v22 | 7/7 | — | — | — | — |
| v22 | v22 | base | 6/7 | 5 | `"."` | `"</s>"` | -4.75 |
| v22 | v22 | v22 | 7/7 | — | — | — | — |

## wb01-linked_location-ood-0056/s0/unaffected

Mode: unaffected; target: `Nlnvzyaype.`.

Memory:

```text
Nfaghcptvy is at Nlvynziims.
Nrzdlstzsl is owned by Nfaghcptvy.
Nbnkdztqwd is owned by Ncjmdaonse.
Ncjmdaonse is at Nlnvzyaype.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nbnkdztqwd?
```

Historical base generation (eos):

```text
Nlnvzyaype
```

Historical v22 generation (eos):

```text
Nlnvzyaype.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -5.875 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -5.375 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -5.75 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -5.375 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-linked_location-ood-0056/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Ngordxmalv is at Nvtdjekcqs.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nrzdlstzsl?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 4/4 | — | — | — | — |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 4/4 | — | — | — | — |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 4/4 | — | — | — | — |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 4/4 | — | — | — | — |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-linked_location-ood-0056/s1/affected

Mode: affected; target: `Norgyuyony.`.

Memory:

```text
Nfaghcptvy is at Norgyuyony.
Nrzdlstzsl is owned by Nfaghcptvy.
Nbnkdztqwd is owned by Ncjmdaonse.
Ncjmdaonse is at Nlnvzyaype.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nrzdlstzsl?
```

Historical base generation (eos):

```text
Ngyuyonygy.
```

Historical v22 generation (eos):

```text
Ngyuyony.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 4/6 | 0 | `"Nor"` | `"N"` | -6.75 |
| base | base | v22 | 5/6 | 0 | `"Nor"` | `"N"` | -2 |
| base | v22 | base | 4/6 | 0 | `"Nor"` | `"N"` | -6.25 |
| base | v22 | v22 | 5/6 | 0 | `"Nor"` | `"N"` | -2 |
| v22 | base | base | 4/6 | 0 | `"Nor"` | `"N"` | -7.125 |
| v22 | base | v22 | 5/6 | 0 | `"Nor"` | `"N"` | -2 |
| v22 | v22 | base | 4/6 | 0 | `"Nor"` | `"N"` | -6.75 |
| v22 | v22 | v22 | 5/6 | 0 | `"Nor"` | `"N"` | -2.125 |

## wb01-linked_location-ood-0056/s1/unaffected

Mode: unaffected; target: `Nlnvzyaype.`.

Memory:

```text
Nfaghcptvy is at Norgyuyony.
Nrzdlstzsl is owned by Nfaghcptvy.
Nbnkdztqwd is owned by Ncjmdaonse.
Ncjmdaonse is at Nlnvzyaype.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nbnkdztqwd?
```

Historical base generation (eos):

```text
Nlnvzyaype
```

Historical v22 generation (eos):

```text
Nlnvzyaype.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -4.75 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -4.25 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -4.625 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -4.25 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-linked_location-ood-0058/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nizooacxrl?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 4/4 | — | — | — | — |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -0.125 |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-linked_location-ood-0058/s0/affected

Mode: affected; target: `Ndojyaptgn.`.

Memory:

```text
Nizooacxrl is owned by Nqtkfepcrk.
Nzgaohdxdq is owned by Nhwyspcdyf.
Nhwyspcdyf is at Njkkqvkind.
Nqtkfepcrk is at Ndojyaptgn.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nizooacxrl?
```

Historical base generation (eos):

```text
Ndojyaptgn (Nqtkfepcrk)
```

Historical v22 generation (eos):

```text
Ndojyaptgn.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"("` | -4.0625 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -3.25 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -3.9375 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -3.25 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-linked_location-ood-0058/s0/unaffected

Mode: unaffected; target: `Njkkqvkind.`.

Memory:

```text
Nizooacxrl is owned by Nqtkfepcrk.
Nzgaohdxdq is owned by Nhwyspcdyf.
Nhwyspcdyf is at Njkkqvkind.
Nqtkfepcrk is at Ndojyaptgn.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nzgaohdxdq?
```

Historical base generation (eos):

```text
Ndojyaptgn
```

Historical v22 generation (eos):

```text
Ndojyaptgn.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 1 | `"j"` | `"do"` | -3.875 |
| base | base | v22 | 7/8 | 1 | `"j"` | `"do"` | -0.625 |
| base | v22 | base | 6/8 | 1 | `"j"` | `"do"` | -3.5 |
| base | v22 | v22 | 7/8 | 1 | `"j"` | `"do"` | -0.375 |
| v22 | base | base | 6/8 | 1 | `"j"` | `"do"` | -3.75 |
| v22 | base | v22 | 7/8 | 1 | `"j"` | `"do"` | -0.5 |
| v22 | v22 | base | 6/8 | 1 | `"j"` | `"do"` | -3.25 |
| v22 | v22 | v22 | 7/8 | 1 | `"j"` | `"do"` | -0.625 |

## wb01-linked_location-ood-0058/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Nimxjrchhp is at Najmaqisql.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nizooacxrl?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 4/4 | — | — | — | — |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 4/4 | — | — | — | — |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 4/4 | — | — | — | — |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 4/4 | — | — | — | — |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-linked_location-ood-0058/s1/affected

Mode: affected; target: `Nymszrcrff.`.

Memory:

```text
Nizooacxrl is owned by Nqtkfepcrk.
Nzgaohdxdq is owned by Nhwyspcdyf.
Nhwyspcdyf is at Njkkqvkind.
Nqtkfepcrk is at Nymszrcrff.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nizooacxrl?
```

Historical base generation (eos):

```text
Nymszrcrff
```

Historical v22 generation (eos):

```text
Nymszrcrk.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -6.4375 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -5.8125 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -6.3125 |
| v22 | base | v22 | 7/8 | 5 | `"ff"` | `"k"` | -1 |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -5.75 |
| v22 | v22 | v22 | 7/8 | 5 | `"ff"` | `"k"` | -1.625 |

## wb01-linked_location-ood-0058/s1/unaffected

Mode: unaffected; target: `Njkkqvkind.`.

Memory:

```text
Nizooacxrl is owned by Nqtkfepcrk.
Nzgaohdxdq is owned by Nhwyspcdyf.
Nhwyspcdyf is at Njkkqvkind.
Nqtkfepcrk is at Nymszrcrff.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is the owner of Nzgaohdxdq?
```

Historical base generation (eos):

```text
Nymszrcrff
```

Historical v22 generation (eos):

```text
Nymszrcrff.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 0 | `"N"` | `"Ny"` | -2.875 |
| base | base | v22 | 7/8 | 0 | `"N"` | `"Ny"` | -2.875 |
| base | v22 | base | 6/8 | 0 | `"N"` | `"Ny"` | -3 |
| base | v22 | v22 | 7/8 | 0 | `"N"` | `"Ny"` | -2.875 |
| v22 | base | base | 6/8 | 0 | `"N"` | `"Ny"` | -3 |
| v22 | base | v22 | 7/8 | 0 | `"N"` | `"Ny"` | -3 |
| v22 | v22 | base | 6/8 | 0 | `"N"` | `"Ny"` | -3.125 |
| v22 | v22 | v22 | 7/8 | 0 | `"N"` | `"Ny"` | -3 |

## wb01-location-test-0013/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is Nsxhziubst?
```

Historical base generation (eos):

```text
Not specified
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 3/4 | 2 | `"."` | `"</s>"` | -1 |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -1.375 |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-location-test-0013/s0/affected

Mode: affected; target: `Nybcfejpyg.`.

Memory:

```text
Nkuviveiel is at Nvzwtaiamu.
Nsxhziubst is at Nybcfejpyg.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is Nsxhziubst?
```

Historical base generation (eos):

```text
Nybcfejpyg
```

Historical v22 generation (eos):

```text
Nybcfejpyg.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -7.9375 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -7.1875 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -7.5625 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -6.6875 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-location-test-0013/s0/unaffected

Mode: unaffected; target: `Nvzwtaiamu.`.

Memory:

```text
Nkuviveiel is at Nvzwtaiamu.
Nsxhziubst is at Nybcfejpyg.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is Nkuviveiel?
```

Historical base generation (eos):

```text
Nvzwtaiamu
```

Historical v22 generation (eos):

```text
Nvzwtaiamu.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -8.875 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -8 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -8.5 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -7.125 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-location-test-0013/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Ndaagbwhhp is at Nhyudqucuu.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is Nsxhziubst?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 4/4 | — | — | — | — |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 4/4 | — | — | — | — |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 4/4 | — | — | — | — |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 4/4 | — | — | — | — |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-location-test-0013/s1/affected

Mode: affected; target: `Neuiatciqh.`.

Memory:

```text
Nkuviveiel is at Nvzwtaiamu.
Nsxhziubst is at Neuiatciqh.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is Nsxhziubst?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Neuiatciqh.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 0 | `"Ne"` | `"Not"` | 0 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -5.875 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -6.9375 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -5.375 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-location-test-0013/s1/unaffected

Mode: unaffected; target: `Nvzwtaiamu.`.

Memory:

```text
Nkuviveiel is at Nvzwtaiamu.
Nsxhziubst is at Neuiatciqh.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is Nkuviveiel?
```

Historical base generation (eos):

```text
Nvzwtaiamu
```

Historical v22 generation (eos):

```text
Nvzwtaiamu.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -7.9375 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -6.5 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -7.375 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -6.125 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-location-test-0014/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is Njcprnaekj?
```

Historical base generation (eos):

```text
Not specified
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 3/4 | 2 | `"."` | `"</s>"` | -0.75 |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -1.25 |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-location-test-0014/s0/affected

Mode: affected; target: `Niqlwkkjde.`.

Memory:

```text
Nbsnunfxbz is at Nsoerlpveo.
Njcprnaekj is at Niqlwkkjde.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is Njcprnaekj?
```

Historical base generation (eos):

```text
Niqlwkkjde
```

Historical v22 generation (eos):

```text
Niqlwkkjde.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -8.25 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -7.375 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -8 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -7.1875 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-location-test-0014/s0/unaffected

Mode: unaffected; target: `Nsoerlpveo.`.

Memory:

```text
Nbsnunfxbz is at Nsoerlpveo.
Njcprnaekj is at Niqlwkkjde.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is Nbsnunfxbz?
```

Historical base generation (eos):

```text
Nsoerlpveo
```

Historical v22 generation (eos):

```text
Nsoerlpveo.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -6.5 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -5.625 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -6.5 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -5.625 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-location-test-0014/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Ndvgfcyamy is at Nqvbkgygdx.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is Njcprnaekj?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 4/4 | — | — | — | — |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 4/4 | — | — | — | — |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 4/4 | — | — | — | — |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 4/4 | — | — | — | — |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-location-test-0014/s1/affected

Mode: affected; target: `Nfanutcokf.`.

Memory:

```text
Nbsnunfxbz is at Nsoerlpveo.
Njcprnaekj is at Nfanutcokf.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is Njcprnaekj?
```

Historical base generation (eos):

```text
Njcprnaekj is at Nsoerlpveo.
```

Historical v22 generation (eos):

```text
Nfanutcokf.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 1 | `"fan"` | `"j"` | -1.375 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 6/8 | 1 | `"fan"` | `"so"` | -0.125 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 6/8 | 1 | `"fan"` | `"j"` | -1 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -3.25 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-location-test-0014/s1/unaffected

Mode: unaffected; target: `Nsoerlpveo.`.

Memory:

```text
Nbsnunfxbz is at Nsoerlpveo.
Njcprnaekj is at Nfanutcokf.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Where is Nbsnunfxbz?
```

Historical base generation (eos):

```text
Nsoerlpveo
```

Historical v22 generation (eos):

```text
Nsoerlpveo.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -5.5 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -4.625 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -5.375 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -4.625 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-order-test-0002/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Njhxbkoglo or Nukunqizcl?
```

Historical base generation (eos):

```text
Not specified
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 2/4 | 2 | `"."` | `"</s>"` | -1 |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -1.625 |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-order-test-0002/s0/affected

Mode: affected; target: `Njhxbkoglo.`.

Memory:

```text
Nukunqizcl is ranked above Njgybcmbzt.
Nlbslydwiv is ranked above Nukunqizcl.
Njhxbkoglo is ranked above Nlbslydwiv.
Njgybcmbzt is ranked above Nmwkzgzeme.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Njhxbkoglo or Nukunqizcl?
```

Historical base generation (eos):

```text
Njhxbkoglo is ranked higher.
```

Historical v22 generation (eos):

```text
Njhxbkoglo.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 8/9 | 7 | `"."` | `"is"` | -12.1875 |
| base | base | v22 | 9/9 | — | — | — | — |
| base | v22 | base | 8/9 | 7 | `"."` | `"is"` | -11.3125 |
| base | v22 | v22 | 9/9 | — | — | — | — |
| v22 | base | base | 8/9 | 7 | `"."` | `"is"` | -12 |
| v22 | base | v22 | 9/9 | — | — | — | — |
| v22 | v22 | base | 8/9 | 7 | `"."` | `"is"` | -11.3125 |
| v22 | v22 | v22 | 9/9 | — | — | — | — |

## wb01-order-test-0002/s0/unaffected

Mode: unaffected; target: `Njgybcmbzt.`.

Memory:

```text
Nukunqizcl is ranked above Njgybcmbzt.
Nlbslydwiv is ranked above Nukunqizcl.
Njhxbkoglo is ranked above Nlbslydwiv.
Njgybcmbzt is ranked above Nmwkzgzeme.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Njgybcmbzt or Nmwkzgzeme?
```

Historical base generation (eos):

```text
Njgybcmbzt
```

Historical v22 generation (eos):

```text
Njgybcmbzt.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -11 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -11.1875 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -11.25 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -11.1875 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-order-test-0002/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Nwvwntipiu is at Naoujlofcp.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Njhxbkoglo or Nukunqizcl?
```

Historical base generation (length):

```text
Not specified (The memory facts provided do not include the necessary information to compare the rankings of Njhxbk
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 2/4 | 2 | `"."` | `"("` | -1.5 |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 2/4 | 2 | `"."` | `"</s>"` | -1.375 |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 2/4 | 2 | `"."` | `"("` | -1.5 |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 2/4 | 2 | `"."` | `"</s>"` | -1.125 |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-order-test-0002/s1/affected

Mode: affected; target: `Nukunqizcl.`.

Memory:

```text
Njhxbkoglo is ranked above Njgybcmbzt.
Nlbslydwiv is ranked above Njhxbkoglo.
Nukunqizcl is ranked above Nlbslydwiv.
Njgybcmbzt is ranked above Nmwkzgzeme.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Njhxbkoglo or Nukunqizcl?
```

Historical base generation (eos):

```text
Nukunqizcl is ranked higher.
```

Historical v22 generation (eos):

```text
Nukunqizcl.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"is"` | -11.4375 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -11.125 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"is"` | -11.375 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -11.25 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-order-test-0002/s1/unaffected

Mode: unaffected; target: `Njgybcmbzt.`.

Memory:

```text
Njhxbkoglo is ranked above Njgybcmbzt.
Nlbslydwiv is ranked above Njhxbkoglo.
Nukunqizcl is ranked above Nlbslydwiv.
Njgybcmbzt is ranked above Nmwkzgzeme.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Njgybcmbzt or Nmwkzgzeme?
```

Historical base generation (eos):

```text
Njgybcmbzt is ranked higher.
```

Historical v22 generation (eos):

```text
Njgybcmbzt.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"is"` | -11.5625 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -11.125 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"is"` | -11.5 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -11 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-order-test-0007/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Nnzfosszql or Nwpkirypuq?
```

Historical base generation (eos):

```text
Not specified (The memory facts provided do not include a ranking for these specific strings.)
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 2/4 | 2 | `"."` | `"("` | -0.875 |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -1.625 |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-order-test-0007/s0/affected

Mode: affected; target: `Nnzfosszql.`.

Memory:

```text
Nbzfnerjmv is ranked above Nahcvzocje.
Nnzfosszql is ranked above Nonfrecqxb.
Nwpkirypuq is ranked above Nbzfnerjmv.
Nonfrecqxb is ranked above Nwpkirypuq.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Nnzfosszql or Nwpkirypuq?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Nnzfosszql.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/9 | 0 | `"N"` | `"Not"` | -1.25 |
| base | base | v22 | 9/9 | — | — | — | — |
| base | v22 | base | 7/9 | 0 | `"N"` | `"Not"` | -1 |
| base | v22 | v22 | 9/9 | — | — | — | — |
| v22 | base | base | 7/9 | 0 | `"N"` | `"Not"` | -0.75 |
| v22 | base | v22 | 9/9 | — | — | — | — |
| v22 | v22 | base | 7/9 | 0 | `"N"` | `"Not"` | -0.625 |
| v22 | v22 | v22 | 9/9 | — | — | — | — |

## wb01-order-test-0007/s0/unaffected

Mode: unaffected; target: `Nbzfnerjmv.`.

Memory:

```text
Nbzfnerjmv is ranked above Nahcvzocje.
Nnzfosszql is ranked above Nonfrecqxb.
Nwpkirypuq is ranked above Nbzfnerjmv.
Nonfrecqxb is ranked above Nwpkirypuq.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Nbzfnerjmv or Nahcvzocje?
```

Historical base generation (eos):

```text
Nahcvzocje
```

Historical v22 generation (eos):

```text
Nahcvzocje.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/9 | 0 | `"N"` | `"Nah"` | -5.625 |
| base | base | v22 | 8/9 | 0 | `"N"` | `"Nah"` | -2.5 |
| base | v22 | base | 7/9 | 0 | `"N"` | `"Nah"` | -6.125 |
| base | v22 | v22 | 8/9 | 0 | `"N"` | `"Nah"` | -2.75 |
| v22 | base | base | 7/9 | 0 | `"N"` | `"Nah"` | -5.875 |
| v22 | base | v22 | 8/9 | 0 | `"N"` | `"Nah"` | -2.75 |
| v22 | v22 | base | 7/9 | 0 | `"N"` | `"Nah"` | -6.375 |
| v22 | v22 | v22 | 8/9 | 0 | `"N"` | `"Nah"` | -3 |

## wb01-order-test-0007/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Nmzbetubjm is at Ndmwpzjwiw.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Nnzfosszql or Nwpkirypuq?
```

Historical base generation (length):

```text
Not specified (The given memory facts do not provide enough information to compare the rank of Nnzfosszql
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 2/4 | 2 | `"."` | `"("` | -0.5 |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 2/4 | 2 | `"."` | `"("` | -0.5 |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 2/4 | 2 | `"."` | `"("` | -0.875 |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 2/4 | 2 | `"."` | `"("` | -0.375 |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-order-test-0007/s1/affected

Mode: affected; target: `Nwpkirypuq.`.

Memory:

```text
Nbzfnerjmv is ranked above Nahcvzocje.
Nwpkirypuq is ranked above Nonfrecqxb.
Nnzfosszql is ranked above Nbzfnerjmv.
Nonfrecqxb is ranked above Nnzfosszql.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Nnzfosszql or Nwpkirypuq?
```

Historical base generation (eos):

```text
Nwpkirypuq is ranked higher.
```

Historical v22 generation (eos):

```text
Nwpkirypuq.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"is"` | -11.25 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -10.4375 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"is"` | -10.9375 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -10.4375 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-order-test-0007/s1/unaffected

Mode: unaffected; target: `Nbzfnerjmv.`.

Memory:

```text
Nbzfnerjmv is ranked above Nahcvzocje.
Nwpkirypuq is ranked above Nonfrecqxb.
Nnzfosszql is ranked above Nbzfnerjmv.
Nonfrecqxb is ranked above Nnzfosszql.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Which is ranked higher, Nbzfnerjmv or Nahcvzocje?
```

Historical base generation (eos):

```text
Nahcvzocje
```

Historical v22 generation (eos):

```text
Nahcvzocje.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/9 | 0 | `"N"` | `"Nah"` | -4.375 |
| base | base | v22 | 8/9 | 0 | `"N"` | `"Nah"` | -2.25 |
| base | v22 | base | 7/9 | 0 | `"N"` | `"Nah"` | -4.875 |
| base | v22 | v22 | 8/9 | 0 | `"N"` | `"Nah"` | -2.125 |
| v22 | base | base | 7/9 | 0 | `"N"` | `"Nah"` | -4.5 |
| v22 | base | v22 | 8/9 | 0 | `"N"` | `"Nah"` | -2.25 |
| v22 | v22 | base | 7/9 | 0 | `"N"` | `"Nah"` | -5.25 |
| v22 | v22 | v22 | 8/9 | 0 | `"N"` | `"Nah"` | -2.5 |

## wb01-ownership-test-0002/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Who owns Nvpabhqvrz?
```

Historical base generation (eos):

```text
Not specified
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 3/4 | 2 | `"."` | `"</s>"` | 0 |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | -0.25 |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-ownership-test-0002/s0/affected

Mode: affected; target: `Nleptpcktw.`.

Memory:

```text
Nmggxtjikt is owned by Nnrrtojncs.
Nvpabhqvrz is owned by Nleptpcktw.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Who owns Nvpabhqvrz?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Nleptpcktw.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 0 | `"N"` | `"Not"` | -5.875 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 6/8 | 0 | `"N"` | `"Not"` | -4.125 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 6/8 | 0 | `"N"` | `"Not"` | -5.125 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 6/8 | 0 | `"N"` | `"Not"` | -3.875 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-ownership-test-0002/s0/unaffected

Mode: unaffected; target: `Nnrrtojncs.`.

Memory:

```text
Nmggxtjikt is owned by Nnrrtojncs.
Nvpabhqvrz is owned by Nleptpcktw.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Who owns Nmggxtjikt?
```

Historical base generation (eos):

```text
Nnrrtojncs
```

Historical v22 generation (eos):

```text
Nnrrtojncs.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 8/9 | 7 | `"."` | `"</s>"` | -9.5625 |
| base | base | v22 | 9/9 | — | — | — | — |
| base | v22 | base | 8/9 | 7 | `"."` | `"</s>"` | -9.125 |
| base | v22 | v22 | 9/9 | — | — | — | — |
| v22 | base | base | 8/9 | 7 | `"."` | `"</s>"` | -9.5 |
| v22 | base | v22 | 9/9 | — | — | — | — |
| v22 | v22 | base | 8/9 | 7 | `"."` | `"</s>"` | -8.8125 |
| v22 | v22 | v22 | 9/9 | — | — | — | — |

## wb01-ownership-test-0002/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Npcvghgcbx is at Nymzqvqmpq.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Who owns Nvpabhqvrz?
```

Historical base generation (eos):

```text
Not specified (The provided memory facts do not include information about the ownership of Nvpabhqvrz.)
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 3/4 | 2 | `"."` | `"("` | -0.625 |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 4/4 | — | — | — | — |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 3/4 | 2 | `"."` | `"("` | -0.5 |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 4/4 | — | — | — | — |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-ownership-test-0002/s1/affected

Mode: affected; target: `Nuqkcacpxn.`.

Memory:

```text
Nmggxtjikt is owned by Nnrrtojncs.
Nvpabhqvrz is owned by Nuqkcacpxn.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Who owns Nvpabhqvrz?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Nuqkcacpxn.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 0 | `"Nu"` | `"Not"` | -11.0625 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 6/8 | 0 | `"Nu"` | `"Not"` | -8.75 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 6/8 | 0 | `"Nu"` | `"Not"` | -10.3125 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 6/8 | 0 | `"Nu"` | `"Not"` | -8.375 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-ownership-test-0002/s1/unaffected

Mode: unaffected; target: `Nnrrtojncs.`.

Memory:

```text
Nmggxtjikt is owned by Nnrrtojncs.
Nvpabhqvrz is owned by Nuqkcacpxn.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Who owns Nmggxtjikt?
```

Historical base generation (eos):

```text
Nnrrtojncs
```

Historical v22 generation (eos):

```text
Nnrrtojncs.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 8/9 | 7 | `"."` | `"</s>"` | -9.625 |
| base | base | v22 | 9/9 | — | — | — | — |
| base | v22 | base | 8/9 | 7 | `"."` | `"</s>"` | -9.1875 |
| base | v22 | v22 | 9/9 | — | — | — | — |
| v22 | base | base | 8/9 | 7 | `"."` | `"</s>"` | -9.5 |
| v22 | base | v22 | 9/9 | — | — | — | — |
| v22 | v22 | base | 8/9 | 7 | `"."` | `"</s>"` | -8.875 |
| v22 | v22 | v22 | 9/9 | — | — | — | — |

## wb01-ownership-test-0011/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Who owns Nohldhvrwm?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 4/4 | — | — | — | — |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 3/4 | 2 | `"."` | `"</s>"` | 0 |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-ownership-test-0011/s0/affected

Mode: affected; target: `Nubloyqbus.`.

Memory:

```text
Nohldhvrwm is owned by Nubloyqbus.
Njeabfhzkj is owned by Nblpcokgxk.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Who owns Nohldhvrwm?
```

Historical base generation (eos):

```text
Nubloyqbus
```

Historical v22 generation (eos):

```text
Nubloyqbus.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -5.75 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -6.125 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -6.125 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -6.0625 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-ownership-test-0011/s0/unaffected

Mode: unaffected; target: `Nblpcokgxk.`.

Memory:

```text
Nohldhvrwm is owned by Nubloyqbus.
Njeabfhzkj is owned by Nblpcokgxk.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Who owns Njeabfhzkj?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Nblpcokgxk.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/9 | 0 | `"N"` | `"Not"` | -6.75 |
| base | base | v22 | 9/9 | — | — | — | — |
| base | v22 | base | 7/9 | 0 | `"N"` | `"Not"` | -5 |
| base | v22 | v22 | 9/9 | — | — | — | — |
| v22 | base | base | 7/9 | 0 | `"N"` | `"Not"` | -6 |
| v22 | base | v22 | 9/9 | — | — | — | — |
| v22 | v22 | base | 7/9 | 0 | `"N"` | `"Not"` | -4.5 |
| v22 | v22 | v22 | 9/9 | — | — | — | — |

## wb01-ownership-test-0011/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Nrhbykuoon is at Nllzhecedw.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Who owns Nohldhvrwm?
```

Historical base generation (eos):

```text
Not specified (The provided memory facts do not include information about the ownership of Nohldhvrwm.)
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 2/4 | 2 | `"."` | `"("` | -1.25 |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 4/4 | — | — | — | — |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 3/4 | 2 | `"."` | `"("` | -1 |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 4/4 | — | — | — | — |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-ownership-test-0011/s1/affected

Mode: affected; target: `Nbrgewwfim.`.

Memory:

```text
Nohldhvrwm is owned by Nbrgewwfim.
Njeabfhzkj is owned by Nblpcokgxk.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Who owns Nohldhvrwm?
```

Historical base generation (eos):

```text
Nbrgewwfim
```

Historical v22 generation (eos):

```text
Nbrgewwfim.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -6.75 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -6.6875 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -6.6875 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -6.4375 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-ownership-test-0011/s1/unaffected

Mode: unaffected; target: `Nblpcokgxk.`.

Memory:

```text
Nohldhvrwm is owned by Nbrgewwfim.
Njeabfhzkj is owned by Nblpcokgxk.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. Who owns Njeabfhzkj?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Nblpcokgxk.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/9 | 0 | `"N"` | `"Not"` | -5.125 |
| base | base | v22 | 9/9 | — | — | — | — |
| base | v22 | base | 7/9 | 0 | `"N"` | `"Not"` | -4 |
| base | v22 | v22 | 9/9 | — | — | — | — |
| v22 | base | base | 7/9 | 0 | `"N"` | `"Not"` | -4 |
| v22 | base | v22 | 9/9 | — | — | — | — |
| v22 | v22 | base | 7/9 | 0 | `"N"` | `"Not"` | -2.75 |
| v22 | v22 | v22 | 9/9 | — | — | — | — |

## wb01-revision-test-0009/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. At the greatest recorded version number, where is Ndszdknopx?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 4/4 | — | — | — | — |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 4/4 | — | — | — | — |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-revision-test-0009/s0/affected

Mode: affected; target: `Ncdcwzomlj.`.

Memory:

```text
Version 1: Nteshuafkn is at Nobiylyndz.
Version 1: Ndszdknopx is at Nzjehmeijk.
Version 2: Ndszdknopx is at Ncdcwzomlj.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. At the greatest recorded version number, where is Ndszdknopx?
```

Historical base generation (eos):

```text
Ncdcwzomlj
```

Historical v22 generation (eos):

```text
Ncdcwzomlj.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 8/9 | 7 | `"."` | `"</s>"` | -7.75 |
| base | base | v22 | 9/9 | — | — | — | — |
| base | v22 | base | 8/9 | 7 | `"."` | `"</s>"` | -7.125 |
| base | v22 | v22 | 9/9 | — | — | — | — |
| v22 | base | base | 8/9 | 7 | `"."` | `"</s>"` | -7.8125 |
| v22 | base | v22 | 9/9 | — | — | — | — |
| v22 | v22 | base | 8/9 | 7 | `"."` | `"</s>"` | -7.25 |
| v22 | v22 | v22 | 9/9 | — | — | — | — |

## wb01-revision-test-0009/s0/unaffected

Mode: unaffected; target: `Nobiylyndz.`.

Memory:

```text
Version 1: Nteshuafkn is at Nobiylyndz.
Version 1: Ndszdknopx is at Nzjehmeijk.
Version 2: Ndszdknopx is at Ncdcwzomlj.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. At the greatest recorded version number, where is Nteshuafkn?
```

Historical base generation (eos):

```text
Nzjehmeijk
```

Historical v22 generation (eos):

```text
Nobiylyndz.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 5/7 | 0 | `"Nob"` | `"N"` | -0.5 |
| base | base | v22 | 7/7 | — | — | — | — |
| base | v22 | base | 6/7 | 5 | `"."` | `"</s>"` | -8.8125 |
| base | v22 | v22 | 7/7 | — | — | — | — |
| v22 | base | base | 5/7 | 0 | `"Nob"` | `"N"` | -0.375 |
| v22 | base | v22 | 7/7 | — | — | — | — |
| v22 | v22 | base | 6/7 | 5 | `"."` | `"</s>"` | -8.8125 |
| v22 | v22 | v22 | 7/7 | — | — | — | — |

## wb01-revision-test-0009/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Nwynyrjxum is at Nhxzwwxctk.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. At the greatest recorded version number, where is Ndszdknopx?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 4/4 | — | — | — | — |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 4/4 | — | — | — | — |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 4/4 | — | — | — | — |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 4/4 | — | — | — | — |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-revision-test-0009/s1/affected

Mode: affected; target: `Nptltpauge.`.

Memory:

```text
Version 1: Nteshuafkn is at Nobiylyndz.
Version 1: Ndszdknopx is at Nzjehmeijk.
Version 2: Ndszdknopx is at Nptltpauge.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. At the greatest recorded version number, where is Ndszdknopx?
```

Historical base generation (eos):

```text
Nptltpauge
```

Historical v22 generation (eos):

```text
Nptltpauge.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/7 | 5 | `"."` | `"</s>"` | -9.1875 |
| base | base | v22 | 7/7 | — | — | — | — |
| base | v22 | base | 6/7 | 5 | `"."` | `"</s>"` | -8.375 |
| base | v22 | v22 | 7/7 | — | — | — | — |
| v22 | base | base | 6/7 | 5 | `"."` | `"</s>"` | -8.875 |
| v22 | base | v22 | 7/7 | — | — | — | — |
| v22 | v22 | base | 6/7 | 5 | `"."` | `"</s>"` | -8.25 |
| v22 | v22 | v22 | 7/7 | — | — | — | — |

## wb01-revision-test-0009/s1/unaffected

Mode: unaffected; target: `Nobiylyndz.`.

Memory:

```text
Version 1: Nteshuafkn is at Nobiylyndz.
Version 1: Ndszdknopx is at Nzjehmeijk.
Version 2: Ndszdknopx is at Nptltpauge.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. At the greatest recorded version number, where is Nteshuafkn?
```

Historical base generation (eos):

```text
Nzjehmeijk
```

Historical v22 generation (eos):

```text
Nobiylyndz.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 5/7 | 0 | `"Nob"` | `"N"` | -0.375 |
| base | base | v22 | 7/7 | — | — | — | — |
| base | v22 | base | 6/7 | 5 | `"."` | `"</s>"` | -9.5 |
| base | v22 | v22 | 7/7 | — | — | — | — |
| v22 | base | base | 5/7 | 0 | `"Nob"` | `"N"` | -0.125 |
| v22 | base | v22 | 7/7 | — | — | — | — |
| v22 | v22 | base | 6/7 | 5 | `"."` | `"</s>"` | -9.4375 |
| v22 | v22 | v22 | 7/7 | — | — | — | — |

## wb01-revision-test-0011/s0/absent

Mode: absent; target: `Not specified.`.

Memory:

```text

```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. At the greatest recorded version number, where is Nxjhivhwnb?
```

Historical base generation (length):

```text
Not specified (The memory facts do not include information about the location of Nxjhivhwnb at the
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none | base | base | 2/4 | 2 | `"."` | `"("` | -0.5 |
| none | base | v22 | 4/4 | — | — | — | — |
| none | v22 | base | 4/4 | — | — | — | — |
| none | v22 | v22 | 4/4 | — | — | — | — |

## wb01-revision-test-0011/s0/affected

Mode: affected; target: `Ntfsgcpkfl.`.

Memory:

```text
Version 2: Nxjhivhwnb is at Ntfsgcpkfl.
Version 1: Nxjhivhwnb is at Nghzkxhgqr.
Version 1: Nkupcsqooj is at Ndhlubotrp.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. At the greatest recorded version number, where is Nxjhivhwnb?
```

Historical base generation (eos):

```text
Ntfsgcpkfl
```

Historical v22 generation (eos):

```text
Ntfsgcpkfl.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 8/9 | 7 | `"."` | `"</s>"` | -11.5 |
| base | base | v22 | 9/9 | — | — | — | — |
| base | v22 | base | 8/9 | 7 | `"."` | `"</s>"` | -11.125 |
| base | v22 | v22 | 9/9 | — | — | — | — |
| v22 | base | base | 8/9 | 7 | `"."` | `"</s>"` | -11.1875 |
| v22 | base | v22 | 9/9 | — | — | — | — |
| v22 | v22 | base | 8/9 | 7 | `"."` | `"</s>"` | -10.8125 |
| v22 | v22 | v22 | 9/9 | — | — | — | — |

## wb01-revision-test-0011/s0/unaffected

Mode: unaffected; target: `Ndhlubotrp.`.

Memory:

```text
Version 2: Nxjhivhwnb is at Ntfsgcpkfl.
Version 1: Nxjhivhwnb is at Nghzkxhgqr.
Version 1: Nkupcsqooj is at Ndhlubotrp.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. At the greatest recorded version number, where is Nkupcsqooj?
```

Historical base generation (eos):

```text
Ndhlubotrp
```

Historical v22 generation (eos):

```text
Ndhlubotrp.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 7/8 | 6 | `"."` | `"</s>"` | -8.4375 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -8.375 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -8.125 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -8.125 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-revision-test-0011/s0/unrelated

Mode: unrelated; target: `Not specified.`.

Memory:

```text
Nobdyvnple is at Nbdciwuyqc.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. At the greatest recorded version number, where is Nxjhivhwnb?
```

Historical base generation (length):

```text
Not specified (The memory facts do not provide information about the location of Nxjhivhwnb at the
```

Historical v22 generation (eos):

```text
Not specified.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 2/4 | 2 | `"."` | `"("` | -0.75 |
| base | base | v22 | 4/4 | — | — | — | — |
| base | v22 | base | 4/4 | — | — | — | — |
| base | v22 | v22 | 4/4 | — | — | — | — |
| v22 | base | base | 2/4 | 2 | `"."` | `"("` | -0.5 |
| v22 | base | v22 | 4/4 | — | — | — | — |
| v22 | v22 | base | 4/4 | — | — | — | — |
| v22 | v22 | v22 | 4/4 | — | — | — | — |

## wb01-revision-test-0011/s1/affected

Mode: affected; target: `Nntafdfdmf.`.

Memory:

```text
Version 2: Nxjhivhwnb is at Nntafdfdmf.
Version 1: Nxjhivhwnb is at Nghzkxhgqr.
Version 1: Nkupcsqooj is at Ndhlubotrp.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. At the greatest recorded version number, where is Nxjhivhwnb?
```

Historical base generation (eos):

```text
Nghzkxhgqr
```

Historical v22 generation (eos):

```text
Nntafdfdmf.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 6/8 | 1 | `"nt"` | `"gh"` | -0.375 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 6/8 | 1 | `"nt"` | `"gh"` | -0.25 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 7/8 | 6 | `"."` | `"</s>"` | -11.5625 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -11.0625 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

## wb01-revision-test-0011/s1/unaffected

Mode: unaffected; target: `Ndhlubotrp.`.

Memory:

```text
Version 2: Nxjhivhwnb is at Nntafdfdmf.
Version 1: Nxjhivhwnb is at Nghzkxhgqr.
Version 1: Nkupcsqooj is at Ndhlubotrp.
```

Question (with the original short-answer suffix and chat template):

```text
Use only the supplied memory facts. If they do not determine the answer, reply 'Not specified'. At the greatest recorded version number, where is Nkupcsqooj?
```

Historical base generation (eos):

```text
Not specified.
```

Historical v22 generation (eos):

```text
Ndhlubotrp.
```

| W | Q | R | Gold-prefix top-1 positions | First mismatch index | Target token | Predicted token | Gold margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | base | base | 5/8 | 0 | `"N"` | `"Not"` | -0.375 |
| base | base | v22 | 8/8 | — | — | — | — |
| base | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -8.1875 |
| base | v22 | v22 | 8/8 | — | — | — | — |
| v22 | base | base | 6/8 | 0 | `"N"` | `"Not"` | -0.25 |
| v22 | base | v22 | 8/8 | — | — | — | — |
| v22 | v22 | base | 7/8 | 6 | `"."` | `"</s>"` | -8.1875 |
| v22 | v22 | v22 | 8/8 | — | — | — | — |

# MMLU: every question with any Q/R prediction change

All 570 questions are retained in the raw journals; this panel selects every
prediction-changing case across the four fixed-prefix cells, not only losses.

## mmlu:all:test:1087 — college_computer_science

```text
At time 0, five jobs are available for execution on a single processor, with service times of 25, 15, 5, 3, and 2 time units. Which of the following is the minimum value of the average completion time of these jobs?
```

Gold: C

| Q | R | Prediction | Correct | Ties | A/B/C/D logits |
| --- | --- | --- | --- | --- | --- |
| base | base | C | True | 1 | [18.0, 17.5, 18.125, 17.625] |
| base | v22 | A | False | 2 | [17.75, 17.25, 17.75, 17.25] |
| v22 | base | C | True | 1 | [18.0, 17.5, 18.125, 17.5] |
| v22 | v22 | C | True | 1 | [17.625, 17.25, 17.75, 17.25] |

## mmlu:all:test:13060 — public_relations

```text
Which statement is NOT true of both issues management and crisis management?
```

Gold: B

| Q | R | Prediction | Correct | Ties | A/B/C/D logits |
| --- | --- | --- | --- | --- | --- |
| base | base | A | False | 1 | [17.375, 17.25, 16.625, 16.0] |
| base | v22 | B | True | 1 | [17.0, 17.125, 16.375, 15.875] |
| v22 | base | A | False | 2 | [17.25, 17.25, 16.625, 16.0] |
| v22 | v22 | A | False | 2 | [17.0, 17.0, 16.375, 15.9375] |

## mmlu:all:test:13900 — world_religions

```text
 What is a central component of tantric Buddhism?
```

Gold: D

| Q | R | Prediction | Correct | Ties | A/B/C/D logits |
| --- | --- | --- | --- | --- | --- |
| base | base | D | True | 1 | [12.25, 17.75, 13.3125, 17.875] |
| base | v22 | B | False | 2 | [12.375, 17.625, 13.375, 17.625] |
| v22 | base | B | False | 1 | [12.25, 17.875, 13.375, 17.75] |
| v22 | v22 | B | False | 2 | [12.375, 17.625, 13.3125, 17.625] |

## mmlu:all:test:419 — business_ethics

```text
Predatory pricing.
```

Gold: D

| Q | R | Prediction | Correct | Ties | A/B/C/D logits |
| --- | --- | --- | --- | --- | --- |
| base | base | A | False | 2 | [16.25, 16.25, 15.6875, 15.5] |
| base | v22 | A | False | 1 | [16.125, 16.0, 15.625, 15.625] |
| v22 | base | A | False | 1 | [16.25, 16.125, 15.75, 15.625] |
| v22 | v22 | B | False | 1 | [16.0, 16.125, 15.5625, 15.625] |

## mmlu:all:test:4247 — high_school_mathematics

```text
What is the range of the function $f(x) = \frac{1}{1-x}$? Express your answer in interval notation.
```

Gold: B

| Q | R | Prediction | Correct | Ties | A/B/C/D logits |
| --- | --- | --- | --- | --- | --- |
| base | base | D | False | 1 | [18.875, 18.125, 16.625, 19.0] |
| base | v22 | D | False | 1 | [18.5, 17.625, 16.25, 18.625] |
| v22 | base | A | False | 2 | [18.875, 18.0, 16.5, 18.875] |
| v22 | v22 | D | False | 1 | [18.375, 17.625, 16.25, 18.5] |

## mmlu:all:test:4311 — high_school_mathematics

```text
What is the greatest common factor of 252 and 96?
```

Gold: D

| Q | R | Prediction | Correct | Ties | A/B/C/D logits |
| --- | --- | --- | --- | --- | --- |
| base | base | A | False | 1 | [19.125, 16.5, 19.0, 17.0] |
| base | v22 | C | False | 1 | [18.875, 16.25, 19.0, 16.875] |
| v22 | base | A | False | 1 | [19.25, 16.5, 19.0, 16.875] |
| v22 | v22 | A | False | 1 | [18.75, 16.125, 18.625, 16.75] |

## mmlu:all:test:5462 — high_school_statistics

```text
The president of an online music streaming service whose customers pay a fee wants to gather additional information about customers who have joined in the past 12 months. The company plans to send out an e-mail survey to a sample of current customers with a link that gives participants a month of streaming service for free once the survey has been completed. They know that musical tastes vary by geographical region. Which of the following sample plans would produce the most representative sample of its customers?
```

Gold: D

| Q | R | Prediction | Correct | Ties | A/B/C/D logits |
| --- | --- | --- | --- | --- | --- |
| base | base | B | False | 1 | [13.375, 19.625, 14.5625, 19.5] |
| base | v22 | D | True | 1 | [13.25, 18.875, 14.375, 19.0] |
| v22 | base | B | False | 1 | [13.375, 19.5, 14.5, 19.375] |
| v22 | v22 | B | False | 2 | [13.25, 18.875, 14.3125, 18.875] |

## mmlu:all:test:6906 — machine_learning

```text
K-fold cross-validation is
```

Gold: A

| Q | R | Prediction | Correct | Ties | A/B/C/D logits |
| --- | --- | --- | --- | --- | --- |
| base | base | B | False | 1 | [17.25, 17.75, 16.375, 17.5] |
| base | v22 | B | False | 1 | [16.875, 17.125, 16.0, 17.0] |
| v22 | base | D | False | 1 | [17.0, 17.5, 16.375, 17.625] |
| v22 | v22 | B | False | 2 | [16.75, 17.0, 15.875, 17.0] |

## mmlu:all:test:950 — college_chemistry

```text
Calculate spin density on the central carbon atom of malonic acid radical (•CH(COOH)2) if the hyperfine value for the α-hydrogen atom is 21.9 G.
```

Gold: C

| Q | R | Prediction | Correct | Ties | A/B/C/D logits |
| --- | --- | --- | --- | --- | --- |
| base | base | B | False | 1 | [17.875, 18.0, 17.625, 17.5] |
| base | v22 | A | False | 2 | [17.5, 17.5, 17.375, 17.125] |
| v22 | base | B | False | 1 | [17.875, 18.0, 17.625, 17.5] |
| v22 | v22 | A | False | 2 | [17.5, 17.5, 17.25, 17.0] |

## mmlu:all:test:9596 — nutrition

```text
Which of the following has not at one point in the past few decades been considered as a cause of the oedema of kwashiorkor?

```

Gold: D

| Q | R | Prediction | Correct | Ties | A/B/C/D logits |
| --- | --- | --- | --- | --- | --- |
| base | base | D | True | 1 | [16.625, 17.25, 16.5, 17.375] |
| base | v22 | B | False | 2 | [16.625, 17.125, 16.375, 17.125] |
| v22 | base | B | False | 2 | [16.75, 17.375, 16.5, 17.375] |
| v22 | v22 | B | False | 2 | [16.625, 17.125, 16.375, 17.125] |
