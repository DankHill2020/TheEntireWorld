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
};
