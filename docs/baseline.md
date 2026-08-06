# Osnovica: klasifikacija po EuroVocu

Referentna točka za svaki složeniji model. Oznake dolaze s portala
(polje EuroVoc), nisu ručno dodane. Postupak i mjere opisani su u
`scrapers/baseline.py`.

- Dokumenata: **1274**
- Oznaka (područja s najmanje 30 primjera): **19**
- Prosječno oznaka po dokumentu: 2.9
- Podjela: 955 za učenje, 319 za provjeru
- Značajki nakon TF-IDF: 238529

## Rezultat

| Mjera | Vrijednost |
|---|---|
| Mikro F1 | **0.708** |
| Makro F1 | **0.623** |
| Mikro F1, trivijalno (3 najčešćih oznaka) | 0.393 |

Trivijalna osnovica pokazuje koliko se dobiva pukim pogađanjem
najčešćih oznaka. Svaki model koji je ne nadmašuje uvjerljivo nije
naučio ništa korisno.

## Po oznaci

```
                                 precision    recall  f1-score   support

DRUŠTVENA PITANJA GRADITELJSTVO      0.727     0.762     0.744        21
      DRUŠTVENA PITANJA OBITELJ      0.000     0.000     0.000        10
             FINANCIJE KREDITNE      0.333     0.500     0.400         8
        FINANCIJSKE INSTITUCIJE      0.357     0.625     0.455         8
                  KAZNENO PRAVO      0.667     0.720     0.692        25
                  POLJOPRIVREDA      0.632     0.545     0.585       123
          PRAVO GRAĐANSKO PRAVO      0.827     0.891     0.858       129
            PRAVO KAZNENO PRAVO      0.821     0.958     0.885       120
                PRAVO PRAVOSUĐE      0.846     0.440     0.579        25
                      PRAVOSUĐE      0.757     0.891     0.819       119
      PRIJEVOZ KOPNENI PRIJEVOZ      0.500     0.400     0.444         5
                   RADNI UVJETI      1.000     0.750     0.857        16
 RADNI UVJETI ORGANIZACIJA RADA      1.000     0.733     0.846        15
            RIBARSTVO ŠUMARSTVO      0.580     0.490     0.531       104
  TRGOVINA MEĐUNARODNA TRGOVINA      0.385     1.000     0.556         5
                      URBANIZAM      0.607     0.810     0.694        21
    USTROJ PRAVOSUDNOGA SUSTAVA      0.600     0.529     0.562        17
                  ZAPOŠLJAVANJE      1.000     0.600     0.750        20
                      ŠUMARSTVO      0.632     0.545     0.585       123

                      micro avg      0.712     0.704     0.708       914
                      macro avg      0.646     0.642     0.623       914
                   weighted avg      0.709     0.704     0.698       914
                    samples avg      0.728     0.757     0.691       914

```

## Ograničenja

Korpus je prikupljen ciljano oko šumarske tematike, pa raspodjela
oznaka ne odražava bazu od 1,17 milijuna odluka. Brojke su referentna
točka za ovaj skup, ne procjena za cijelu praksu.
