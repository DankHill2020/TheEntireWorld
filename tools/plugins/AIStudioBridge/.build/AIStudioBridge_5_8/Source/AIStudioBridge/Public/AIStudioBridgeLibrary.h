#pragma once

#include "Kismet/BlueprintFunctionLibrary.h"
#include "Animation/AnimBlueprint.h"
#include "Animation/AnimMontage.h"
#include "Animation/AnimSequence.h"
#include "Engine/Blueprint.h"
#include "InputCoreTypes.h"
#include "AIStudioBridgeLibrary.generated.h"

UCLASS()
class AISTUDIOBRIDGE_API UAIStudioBridgeLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString InspectAnimBlueprintGraph(UAnimBlueprint* AnimBlueprint);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString AddAnimGraphState(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName StateName, UObject* AnimationAsset);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString AddAnimGraphTransitionRule(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName FromState, FName ToState, const FString& RuleExpression);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString DeleteAnimGraphState(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName StateName);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString DeleteAnimGraphTransition(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName FromState, FName ToState);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString RenameAnimGraphState(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName OldStateName, FName NewStateName);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString SetAnimGraphTransitionRule(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName FromState, FName ToState, const FString& RuleExpression);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString SynthesizeAnimGraphTransitionRuleExpression(UAnimBlueprint* AnimBlueprint, FName StateMachineName, FName FromState, FName ToState, const FString& RuleExpression);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString WireAnimGraphOutputPose(UAnimBlueprint* AnimBlueprint, FName StateMachineName);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString CompileAndSaveAnimBlueprint(UAnimBlueprint* AnimBlueprint);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString InspectAnimationSequence(UAnimSequence* Animation);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Runtime")
    static FString InspectCharacterInPIE(UClass* CharacterClass, FString ExpectedAnimClassContains, const TArray<FName>& PropertyNames);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Runtime")
    static FString ValidateCharacterMontagesInPIE(UClass* CharacterClass, const TArray<UAnimMontage*>& Montages, FString ExpectedAnimClassContains);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Runtime")
    static FString InjectKeyInPIE(FKey Key, bool bPressed);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Blueprint")
    static FString DescribeBlueprintNodeAction(UBlueprint* Blueprint, FName GraphName, const FString& NodeWithCategory);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Blueprint")
    static FString SearchBlueprintNodeActions(UBlueprint* Blueprint, FName GraphName, const FString& Query, int32 MaxResults = 50);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Niagara")
    static FString BindNiagaraUserParametersOnBeginPlay(UBlueprint* Blueprint, const TArray<FName>& ComponentNames, const FString& BindingsJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Domain")
    static FString CreateKnownAssetByClassPath(const FString& AssetPath, const FString& ClassPath, const FString& InitialPropertiesJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Domain")
    static FString InspectReflectedAsset(const FString& AssetPath, const TArray<FName>& PropertyNames);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Domain")
    static FString SetReflectedAssetProperty(const FString& AssetPath, FName PropertyName, const FString& ValueJson);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Domain")
    static FString AddObjectReferenceToReflectedArray(const FString& AssetPath, FName PropertyName, const FString& ObjectPath);

    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Domain")
    static FString RemoveObjectReferenceFromReflectedArray(const FString& AssetPath, FName PropertyName, const FString& ObjectPath);
};
