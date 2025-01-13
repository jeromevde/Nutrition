# Data Element Definitions

## GLOBAL Column Definitions
These fields appear in multiple files, and their definition is typically the same unless noted below.

| Table        | Field | Definition of Data Element |
|--------------|-------|----------------------------|
|              | fdc_id | Unique permanent identifier of a food in the food table |
|              | id     | Unique permanent identifier of other kinds of data (e.g., nutrients, lab methods, etc.) in their related table |

## Agricultural Samples
Non-processed foods obtained directly from the location where they are produced.

| Field                | Definition of Data Element                                          | Synonyms                     |
|----------------------|--------------------------------------------------------------------|------------------------------|
| fdc_id               | ID of the food in the food table                                   | FDC Source ID                |
| acquisition_date     | The date this food was obtained                                    |                              |
| market_class         | The name of the specific kind of this food (e.g., "Pinto" for pinto beans) |                              |
| treatment            | Any special condition relevant to the production of this food - typically "drought" or "control" |                              |
| state                | The state in which this food was produced                          |                              |

## Acquisition Samples
Acquisitions may be blended with other acquisitions to create a sample food, and an acquisition can be used to create more than one sample food. This file stores which acquisitions and sample foods are related to each other.

| Field                       | Definition of Data Element                        |
|-----------------------------|--------------------------------------------------|
| fdc_id_of_sample_food       | ID of the sample food that uses the acquisitioned food |
| fdc_id_of_acquisition_food  | ID of the acquisitioned food used in the sample food |

## Branded Food
Foods whose nutrient values are typically obtained from food label data provided by food brand owners.

| Field                       | Definition of Data Element                                                  | Synonyms                     |
|-----------------------------|----------------------------------------------------------------------------|------------------------------|
| fdc_id                      | ID of the food in the food table                                           |                              |
| brand_owner                 | Brand owner for the food                                                   |                              |
| brand_name                  | Brand name for the food                                                    |                              |
| subbrand_name               | Subbrand and variation descriptions                                         |                              |
| gtin_upc                   | GTIN or UPC code identifying the food. Duplicate codes signify an update to the product. Use the publication_date found in the food table to distinguish when each update was published. | GTIN/UPC                     |
| ingredients                 | The list of ingredients (as it appears on the product label)               |                              |
| not_a_significant_source_of | Full text for the "not a significant source of…" label claim               |                              |
| serving_size                | The amount of the serving size when expressed as gram or ml                |                              |
| serving_size_unit           | The unit used to express the serving size (gram or ml)                     |                              |
| household_serving_fulltext  | The amount and unit of serving size when expressed in household units      |                              |
| branded_food_category       | The category of the branded food, assigned by GDSN or Label Insight       |                              |
| data_source                 | The source of the data for this food. GDSN (for GS1) or LI (for Label Insight). |                              |
| package_weight              | Weight of the package                                                      |                              |
| modified_date               | This date reflects when the product data was last modified by the data provider, i.e., the manufacturer |                              |
| available_date              | This is the date when the product record was available for inclusion in the database. |                              |
| discontinued_date           | This is the date when the product was discontinued.                        |                              |
| market_country              | The primary country where the product is marketed.                        |                              |
| preparation_state_code      | Code to describe the preparation of the food. Defined in GS1 link [GS1 Preparation Type Code](https://www.gs1.org/voc/PreparationTypeCode) |                              |
| trade_channel               | Includes a list of locations or programs in which the food is available. Primarily used for Child Nutrition Food Programs |                              |
| short_description           | Manufacturer's short description of the product                           |                              |
| material_code               | The material code for the food, if one is present                         |                              |

## FNDDS Derivation

| Field                  | Definition of Data Element                             |
|------------------------|-------------------------------------------------------|
| derivation_code        | Derivation code as defined by FDC                     |
| derivation_description | The description of the derivation code                 |

## FNDDS Ingredient Nutrient Value

| Field                    | Definition of Data Element                                         |
|--------------------------|-------------------------------------------------------------------|
| ingredient_code          | Identifies only NDB number                                       |
| ingredient_description    | Description of NDB number                                        |
| nutrient_code            | 3-digit identification number                                    |
| nutrient_value           | Amount per 100g edible portion for energy and 64 nutrients      |
| nutrient_value_source    | FDC or other source for nutrient value                          |
| fdc_id                   | Identifier of food in FDC                                       |
| derivation_code          | Derivation code as defined by FDC                               |
| sr_addmod_year           | Year value added or last modified as defined by SR              |
| foundation_year_acquired | Initial year acquired as defined by FDC                         |
| start_date               | Start date of FNDDS version released                            |
| end_date                 | End date of FNDDS version released                              |

## Food
Any substance consumed by humans for nutrition, taste, and/or aroma.

| Field                  | Definition of Data Element                                   | Synonyms                  |
|------------------------|-------------------------------------------------------------|---------------------------|
| fdc_id                 | Unique permanent identifier of the food                     | FDC Source ID             |
| foodClass              | For internal use only                                       |                           |
| data_type              | Type of food data (see Files tab for possible values).     |                           |
| description            | Description of the food                                     |                           |
| food_category_id       | ID of the food category the food belongs to                |                           |
| publication_date       | Date when the food was published to FoodData Central       | Published, Published Date, FDC Published |
| scientific_name        | The scientific name for the food                            |                           |

## Food Attribute
The value for a generic property of a food.

| Field                      | Definition of Data Element                                | Synonyms                     |
|----------------------------|----------------------------------------------------------|------------------------------|
| id                         |                                                          |                              |
| fdc_id                     | ID of the food this food attribute pertains to           |                              |
| seq_num                    | The order the attribute will be displayed on the released food. |                              |
| food_attribute_type_id     | ID of the type of food attribute to which this value is associated for a specific food |                              |
| name                       | Name of food attribute                                   | Changes (on Update Log)      |
| value                      | The actual value of the attribute                        |                              |

## Food Attribute Type
The list of supported attributes associated with a food.

| Field                      | Definition of Data Element                                |
|----------------------------|----------------------------------------------------------|
| id                         |                                                          |
| name                       | Name of the attribute associated with the food - should be displayable to users |
| description                | Description of the attribute                              |

## Food Calorie Conversion Factor
The multiplication factors to be used when calculating energy from macronutrients for a specific food.

| Field                      | Definition of Data Element                                |
|----------------------------|----------------------------------------------------------|
| food_nutrient_conversion_factor_id | ID of the related row in the nutrient_conversion_factor table |
| protein_value              | The multiplication factor for protein                     |
| fat_value                  | The multiplication factor for fat                         |
| carbohydrate_value         | The multiplication factor for carbohydrates               |

## Food Category
Foods of defined similarity.

| Field                      | Definition of Data Element                                |
|----------------------------|----------------------------------------------------------|
| id                         |                                                          |
| code                       | Food group code                                          |
| description                | Description of the food group                            |

## Food Component
A constituent part of a food (e.g., bone is a component of meat).

| Field                      | Definition of Data Element                                | Synonyms        |
|----------------------------|----------------------------------------------------------|------------------|
| id                         |                                                          |                  |
| fdc_id                     | ID of the food this food component pertains to           |                  |
| name                       | The kind of component, e.g., bone                        |                  |
| pct_weight                 | The weight of the component as a percentage of the total weight of the food | Weight (%)       |
| is_refuse                  | Whether the component is refuse, i.e., not edible        | Refuse           |
| gram_weight                | The weight of the component in grams                      | Weight (g)      |
| data_points                | The number of observations on which the measure is based | n                |
| min_year_acquired          | Minimum purchase year of all acquisitions used to derive the component value | Year Acquired    |

## Food Nutrient
A nutrient value for a food.

| Field                      | Definition of Data Element                                | Synonyms        |
|----------------------------|----------------------------------------------------------|------------------|
| id                         |                                                          |                  |
| fdc_id                     | ID of the food this food nutrient pertains to            |                  |
| nutrient_id                | ID of the nutrient to which the food nutrient pertains    |                  |
| amount                     | Amount of the nutrient per 100g of food. Specified in unit defined in the nutrient table. | Average Amount    |
| data_points                | Number of observations on which the value is based       | n                |
| derivation_id              | ID of the food nutrient derivation technique used to derive the value |                  |
| min                        | The minimum amount                                       |


## Agricultural Samples
Non-processed foods obtained directly from the location where they are produced.

| Field                | Definition of Data Element                                          | Synonyms                     |
|----------------------|--------------------------------------------------------------------|------------------------------|
| fdc_id               | ID of the food in the food table                                   | FDC Source ID                |
| acquisition_date     | The date this food was obtained                                    |                              |
| market_class         | The name of the specific kind of this food (e.g., "Pinto" for pinto beans) |                              |
| treatment            | Any special condition relevant to the production of this food - typically "drought" or "control" |                              |
| state                | The state in which this food was produced                          |                              |

## Acquisition Samples
Acquisitions may be blended with other acquisitions to create a sample food, and an acquisition can be used to create more than one sample food. This file stores which acquisitions and sample foods are related to each other.

| Field                       | Definition of Data Element                        |
|-----------------------------|--------------------------------------------------|
| fdc_id_of_sample_food       | ID of the sample food that uses the acquisitioned food |
| fdc_id_of_acquisition_food  | ID of the acquisitioned food used in the sample food |

## Branded Food
Foods whose nutrient values are typically obtained from food label data provided by food brand owners.

| Field                       | Definition of Data Element                                                  | Synonyms                     |
|-----------------------------|----------------------------------------------------------------------------|------------------------------|
| fdc_id                      | ID of the food in the food table                                           |                              |
| brand_owner                 | Brand owner for the food                                                   |                              |
| brand_name                  | Brand name for the food                                                    |                              |
| subbrand_name               | Subbrand and variation descriptions                                         |                              |
| gtin_upc                   | GTIN or UPC code identifying the food. Duplicate codes signify an update to the product. Use the publication_date found in the food table to distinguish when each update was published. | GTIN/UPC                     |
| ingredients                 | The list of ingredients (as it appears on the product label)               |                              |
| not_a_significant_source_of | Full text for the "not a significant source of…" label claim               |                              |
| serving_size                | The amount of the serving size when expressed as gram or ml                |                              |
| serving_size_unit           | The unit used to express the serving size (gram or ml)                     |                              |
| household_serving_fulltext  | The amount and unit of serving size when expressed in household units      |                              |
| branded_food_category       | The category of the branded food, assigned by GDSN or Label Insight       |                              |
| data_source                 | The source of the data for this food. GDSN (for GS1) or LI (for Label Insight). |                              |
| package_weight              | Weight of the package                                                      |                              |
| modified_date               | This date reflects when the product data was last modified by the data provider, i.e., the manufacturer |                              |
| available_date              | This is the date when the product record was available for inclusion in the database. |                              |
| discontinued_date           | This is the date when the product was discontinued.                        |                              |
| market_country              | The primary country where the product is marketed.                        |                              |
| preparation_state_code      | Code to describe the preparation of the food. Defined in GS1 link [GS1 Preparation Type Code](https://www.gs1.org/voc/PreparationTypeCode) |                              |
| trade_channel               | Includes a list of locations or programs in which the food is available. Primarily used for Child Nutrition Food Programs |                              |
| short_description           | Manufacturer's short description of the product                           |                              |
| material_code               | The material code for the food, if one is present                         |                              |

## FNDDS Derivation

| Field                  | Definition of Data Element                             |
|------------------------|-------------------------------------------------------|
| derivation_code        | Derivation code as defined by FDC                     |
| derivation_description | The description of the derivation code                 |

## FNDDS Ingredient Nutrient Value

| Field                    | Definition of Data Element                                         |
|--------------------------|-------------------------------------------------------------------|
| ingredient_code          | Identifies only NDB number                                       |
| ingredient_description    | Description of NDB number                                        |
| nutrient_code            | 3-digit identification number                                    |
| nutrient_value           | Amount per 100g edible portion for energy and 64 nutrients      |
| nutrient_value_source    | FDC or other source for nutrient value                          |
| fdc_id                   | Identifier of food in FDC                                       |
| derivation_code          | Derivation code as defined by FDC                               |
| sr_addmod_year           | Year value added or last modified as defined by SR              |
| foundation_year_acquired | Initial year acquired as defined by FDC                         |
| start_date               | Start date of FNDDS version released                            |
| end_date                 | End date of FNDDS version released                              |

## Food
Any substance consumed by humans for nutrition, taste, and/or aroma.

| Field                  | Definition of Data Element                                   | Synonyms                  |
|------------------------|-------------------------------------------------------------|---------------------------|
| fdc_id                 | Unique permanent identifier of the food                     | FDC Source ID             |
| foodClass              | For internal use only                                       |                           |
| data_type              | Type of food data (see Files tab for possible values).     |                           |
| description            | Description of the food                                     |                           |
| food_category_id       | ID of the food category the food belongs to                |                           |
| publication_date       | Date when the food was published to FoodData Central       | Published, Published Date, FDC Published |
| scientific_name        | The scientific name for the food                            |                           |

## Food Attribute
The value for a generic property of a food.

| Field                      | Definition of Data Element                                | Synonyms                     |
|----------------------------|----------------------------------------------------------|------------------------------|
| id                         |                                                          |                              |
| fdc_id                     | ID of the food this food attribute pertains to           |                              |
| seq_num                    | The order the attribute will be displayed on the released food. |                              |
| food_attribute_type_id     | ID of the type of food attribute to which this value is associated for a specific food |                              |
| name                       | Name of food attribute                                   | Changes (on Update Log)      |
| value                      | The actual value of the attribute                        |                              |

## Food Attribute Type
The list of supported attributes associated with a food.

| Field                      | Definition of Data Element                                |
|----------------------------|----------------------------------------------------------|
| id                         |                                                          |
| name                       | Name of the attribute associated with the food - should be displayable to users |
| description                | Description of the attribute                              |

## Food Calorie Conversion Factor
The multiplication factors to be used when calculating energy from macronutrients for a specific food.

| Field                      | Definition of Data Element                                |
|----------------------------|----------------------------------------------------------|
| food_nutrient_conversion_factor_id | ID of the related row in the nutrient_conversion_factor table |
| protein_value              | The multiplication factor for protein                     |
| fat_value                  | The multiplication factor for fat                         |
| carbohydrate_value         | The multiplication factor for carbohydrates               |

## Food Category
Foods of defined similarity.

| Field                      | Definition of Data Element                                |
|----------------------------|----------------------------------------------------------|
| id                         |                                                          |
| code                       | Food group code                                          |
| description                | Description of the food group                            |

## Food Component
A constituent part of a food (e.g., bone is a component of meat).

| Field                      | Definition of Data Element                                | Synonyms        |
|----------------------------|----------------------------------------------------------|------------------|
| id                         |                                                          |                  |
| fdc_id                     | ID of the food this food component pertains to           |                  |
| name                       | The kind of component, e.g., bone                        |                  |
| pct_weight                 | The weight of the component as a percentage of the total weight of the food | Weight (%)       |
| is_refuse                  | Whether the component is refuse, i.e., not edible        | Refuse           |
| gram_weight                | The weight of the component in grams                      | Weight (g)      |
| data_points                | The number of observations on which the measure is based | n                |
| min_year_acquired          | Minimum purchase year of all acquisitions used to derive the component value | Year Acquired    |

## Food Nutrient
A nutrient value for a food.

| Field                      | Definition of Data Element                                | Synonyms        |
|----------------------------|----------------------------------------------------------|------------------|
| id                         |                                                          |                  |
| fdc_id                     | ID of the food this food nutrient pertains to            |                  |
| nutrient_id                | ID of the nutrient to which the food nutrient pertains    |                  |
| amount                     | Amount of the nutrient per 100g of food. Specified in unit defined in the nutrient table. | Average Amount    |
| data_points                | Number of observations on which the value is based       | n                |
| derivation_id              | ID of the food nutrient derivation technique used to derive the value |                  |
| min                        | The minimum amount                                       |                  |
| max                        | The maximum amount                                       |                  |
| median                     | The median amount                                        |                  |
| loq                       | Limit of quantification as provided by laboratory        |                  |
| footnote                   | Comments on any unusual aspects of the food nutrient. Examples might include why a nutrient value is different than typically expected. |                  |
| min_year_acquired          | Minimum purchase year of all acquisitions used to derive the nutrient value | Year Acquired, Initial Year Acquired |

## Food Nutrient Conversion Factor
Top-level type for all types of nutrient conversion factors. A separate row is stored for each of these 3 types of conversion factors.

| Field                      | Definition of Data Element                                |
|----------------------------|----------------------------------------------------------|
| id                         |                                                          |
| fdc_id                     | ID of the food that this food nutrient conversion factor pertains to |                  |

## Food Nutrient Derivation
Procedure indicating how a food nutrient value was obtained.

| Field                      | Definition of Data Element                                |
|----------------------------|----------------------------------------------------------|
| id                         |                                                          |
| code                       | Code used for the derivation (e.g., A means analytical)  |
| description                | Description of the derivation                            | Deriv. By       |

## Food Nutrient Source
An information source from which we can obtain food nutrient values.

| Field                      | Definition of Data Element                                |
|----------------------------|----------------------------------------------------------|
| id                         |                                                          |
| code                       | Code used for the source (e.g., 4 means calculated or imputed) |                  |
| description                | Description of the source                                 |
