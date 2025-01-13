let foods = null;
let foods_nutrients = null;
let nutrients = null;
let loadingDataPromise = null;


async function fetchCSV(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Could not fetch ${url}, received ${response.status}`);
    }
    const text = await response.text();
    const lines = text.split('\n').map(line => line.trim()).filter(line => line.length > 0);
    const parseCSVLine = (line) => {
        let result = [];
        let currentField = '';
        let inQuotes = false;
        for (let i = 0; i < line.length; i++) {
            let c = line[i];
            if (c === '"' && line[i - 1] !== '\\') {
                inQuotes = !inQuotes;
            } else if (c === ',' && !inQuotes) {
                result.push(currentField);
                currentField = '';
            } else {
                currentField += c;
            }
        }
        result.push(currentField);
        return result.map(field => 
            field.replace(/^"|"$/g, '').replace(/\\"/g, '"').trim()
        );
    };
    const headers = parseCSVLine(lines[0]);
    return lines.slice(1).map(line => {
        const columns = parseCSVLine(line);
        return headers.reduce((obj, header, index) => {
            obj[header] = columns[index] || undefined;
            return obj;
        }, {});
    });
}


async function loadData() {
    if (foods === null || foods_nutrients === null || nutrients === null) {
        if (!loadingDataPromise) {
            loadingDataPromise = (async () => {
                try {
                    const [f_n, f, n] = await Promise.all([
                        fetchCSV('https://jeromevde.github.io/jekyll-blog/2024-08-12-meal-plan/FoodData_Central_October_2024/food_nutrient.csv'),
                        fetchCSV('https://jeromevde.github.io/jekyll-blog/2024-08-12-meal-plan/FoodData_Central_October_2024/food.csv'),
                        fetchCSV('https://jeromevde.github.io/jekyll-blog/2024-08-12-meal-plan/FoodData_Central_October_2024/nutrient.csv')
                    ]);
                    foods_nutrients = f_n;
                    foods = f;
                    nutrients = n;
                } catch (error) {
                    console.error("Error loading data:", error);
                    throw error; // re-throw to handle in caller functions
                } finally {
                    loadingDataPromise = null; // Reset promise so new load can be attempted if needed
                }
            })();
        }
        return loadingDataPromise;
    }
}


async function ensureDataLoaded() {
    if (foods === null || foods_nutrients === null || nutrients === null) {
        await loadData();
    }
}


async function getNutrientsForName(foodName) {
    "use strict";
    await ensureDataLoaded();
    const normalizedFoodName = foodName.toLowerCase();
    const food = foods.find(food => 
        food.description && food.description.toLowerCase() === normalizedFoodName
    );
    if (!food) {
        return { error: "Food not found" };
    }
    const nutrientInfo = foods_nutrients.filter(nutrient => nutrient.fdc_id == food.fdc_id);
    return nutrientInfo.map(nutrient => {
        const nutrientDetail = nutrients.find(n => n.id == nutrient.nutrient_id);
        return {
            name: nutrientDetail ? nutrientDetail.name : 'Unknown Nutrient',
            amount: nutrient.amount || 'N/A',
            unit: nutrientDetail ? nutrientDetail.unit_name : 'Unknown Unit',
            data_points: nutrient.data_points || 'N/A',
            min: nutrient.min || 'N/A',
        };
    });
}

async function findClosestMatches(partialName) {
    await ensureDataLoaded();
    const normalizedPartialName = partialName.toLowerCase();
    return foods
        .filter(food => 
            food.description && 
            food.description.toLowerCase().includes(normalizedPartialName) && 
            food.data_type === "foundation_food"
        )
        .slice(0, 10)
        .map(food => food.description);
}
