using UnrealBuildTool;

public class AIStudioBridge : ModuleRules
{
    public AIStudioBridge(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",
            "CoreUObject",
            "Engine",
            "InputCore",
            "Niagara"
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "UnrealEd",
            "BlueprintGraph",
            "AnimGraph",
            "AnimGraphRuntime",
            "Json",
            "Slate",
            "SlateCore"
        });
    }
}
