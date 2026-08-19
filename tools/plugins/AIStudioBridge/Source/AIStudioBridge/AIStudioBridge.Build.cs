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
            "Niagara",
            "UMG"
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "UnrealEd",
            "UMGEditor",
            "BlueprintGraph",
            "AnimGraph",
            "AnimGraphRuntime",
            "AssetTools",
            "AudioEditor",
            "Json",
            "JsonUtilities",
            "AIGraph",
            "AIModule",
            "BehaviorTreeEditor",
            "NiagaraEditor",
            "PhysicsUtilities",
            "PoseSearch",
            "PoseSearchEditor",
            "Slate",
            "SlateCore"
        });
    }
}
