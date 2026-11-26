So the rule is visible: a declined card is never retried. Only a TimeoutError gets another attempt.

Today the clause changes nothing. It guards against someone later widening the second one to catch every exception.
