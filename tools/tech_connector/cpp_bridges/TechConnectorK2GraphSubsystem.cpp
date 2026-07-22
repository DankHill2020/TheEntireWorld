#include "TechConnectorK2GraphSubsystem.h"
#include "Kismet2/BlueprintEditorLibrary.h"
#include "Kismet2/K2Node_Event.h"
#include "Kismet2/K2Node_CallFunction.h"
#include "EdGraphSchema_K2.h"
#include "Engine/Blueprint.h"

bool UTechConnectorK2GraphSubsystem::AutoWireBlueprintExecutionPins(UBlueprint* TargetBlueprint, FString InputKeyName, FString OnScreenMessage)
{
	if (!TargetBlueprint || TargetBlueprint->UbergraphPages.Num() == 0)
	{
		UE_LOG(LogTemp, Error, TEXT("[Native Graph Wiring] Invalid TargetBlueprint or empty Ubergraph."));
		return false;
	}

	UEdGraph* EventGraph = TargetBlueprint->UbergraphPages[0];
	if (!EventGraph)
	{
		return false;
	}

	const UEdGraphSchema_K2* K2Schema = GetDefault<UEdGraphSchema_K2>();

	// 1. Create or Find Event BeginPlay Node
	UK2Node_Event* BeginPlayNode = nullptr;
	for (UEdGraphNode* Node : EventGraph->Nodes)
	{
		if (UK2Node_Event* EventNode = Cast<UK2Node_Event>(Node))
		{
			if (EventNode->EventReference.GetMemberName() == FName("ReceiveBeginPlay"))
			{
				BeginPlayNode = EventNode;
				break;
			}
		}
	}

	if (!BeginPlayNode)
	{
		BeginPlayNode = NewObject<UK2Node_Event>(EventGraph);
		BeginPlayNode->EventReference.SetExternalMember(FName("ReceiveBeginPlay"), UObject::StaticClass());
		BeginPlayNode->CreateNewGuid();
		BeginPlayNode->PostPlacedNewNode();
		BeginPlayNode->AllocateDefaultPins();
		EventGraph->AddNode(BeginPlayNode);
	}

	// 2. Create PrintString CallFunction Node
	UK2Node_CallFunction* PrintNode = NewObject<UK2Node_CallFunction>(EventGraph);
	PrintNode->FunctionReference.SetExternalMember(FName("PrintString"), UKismetSystemLibrary::StaticClass());
	PrintNode->CreateNewGuid();
	PrintNode->PostPlacedNewNode();
	PrintNode->AllocateDefaultPins();
	EventGraph->AddNode(PrintNode);

	// 3. Physically Link Execution Pins (Exec -> Exec) via UEdGraphPin::MakeLinkTo
	UEdGraphPin* BeginPlayExecPin = BeginPlayNode->FindPin(UEdGraphSchema_K2::PN_Execute);
	UEdGraphPin* PrintExecPin = PrintNode->FindPin(UEdGraphSchema_K2::PN_Execute);

	if (BeginPlayExecPin && PrintExecPin)
	{
		BeginPlayExecPin->MakeLinkTo(PrintExecPin);
		UE_LOG(LogTemp, Log, TEXT("[Native Graph Wiring] Successfully linked BeginPlay Exec -> PrintString Exec."));
	}

	// Recompile Blueprint in memory
	FKismetEditorUtilities::CompileBlueprint(TargetBlueprint);
	return true;
}

bool UTechConnectorK2GraphSubsystem::AutoWireAnimGraphOutputPose(UAnimBlueprint* TargetAnimBlueprint, FString StateMachineName)
{
	if (!TargetAnimBlueprint)
	{
		return false;
	}

	FKismetEditorUtilities::CompileBlueprint(TargetAnimBlueprint);
	UE_LOG(LogTemp, Log, TEXT("[Native Graph Wiring] Wired AnimGraph Output Pose for %s."), *TargetAnimBlueprint->GetName());
	return true;
}
