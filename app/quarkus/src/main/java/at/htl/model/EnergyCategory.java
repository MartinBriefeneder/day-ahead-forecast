package at.htl.model;

public enum EnergyCategory {
    TOTAL("total"),
    COMMUNITY_EFFECTIVE("community_effective"),
    RESIDUAL("residual");

    private final String tagValue;

    EnergyCategory(String tagValue) {
        this.tagValue = tagValue;
    }

    public String tagValue() {
        return tagValue;
    }

    public static EnergyCategory fromTagValue(String value) {
        for (EnergyCategory category : values()) {
            if (category.tagValue.equals(value)) {
                return category;
            }
        }
        throw new IllegalArgumentException("Unsupported energy category: " + value);
    }
}
